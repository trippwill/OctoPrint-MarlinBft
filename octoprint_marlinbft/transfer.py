from binproto2 import FileTransferProtocol, Protocol, FatalError
from octoprint_marlinbft.utils import BftLogger, DeleteUpload, Setting, Phase, SettingsResolver
from time import sleep
try:
    from time import perf_counter
except ImportError:
    # Python < 3.3
    from backports.time_perf_counter import perf_counter


class _FileInfo:

    def __init__(self, local_path, local_basename, remote_basename, local_diskpath):
        self.local_path = local_path
        self.local_basename = local_basename
        self.remote_basename = remote_basename
        self.local_diskpath = local_diskpath

class Process:
    def __init__(self, logger, settings, bft_logger):
        self.logger = logger
        self.settings = SettingsResolver(settings, logger)
        self.bft_logger = bft_logger

    def start(self, handler, local_basename, remote_basename, disk_path, port, baudrate, local_path, **kwargs):
        protocol = None
        fileInfo = None
        start_pc = 0
        try:
            self.logger.info(kwargs)
            self.settings.override_settings = kwargs
            self.logger.info(self.settings.override_settings)
            fileInfo = _FileInfo(local_path, local_basename, remote_basename, disk_path)
            start_pc = perf_counter()
            handler.start(local_basename, remote_basename)
            self.logger.info("Starting transfer process")
            protocol = Protocol(port, baudrate, 512, self.settings.get_int(Setting.CommTimeout), self.bft_logger.copy(prefix="binproto2"))

            wait_after_connect = self.settings.get_int(Setting.WaitAfterConnect)
            if wait_after_connect > 0:
                self.bft_logger.info("waiting %sms after protocol connect" % wait_after_connect)
                sleep(wait_after_connect / 1000)

            protocol.send_ascii("M155 S0")
            protocol.send_ascii("M117 Receiving file " + remote_basename + " ...")
            protocol.connect()

            handler.fire_changed(Phase.Transfer)

            filetransfer = FileTransferProtocol(protocol, logger=self.bft_logger.copy(prefix="fileproto"))
            filetransfer.copy(disk_path, remote_basename, True, False)

            self.bft_logger.info("Finishing up (this could take some time)...")
            protocol.send_ascii("M117 ...Done! %s" % remote_basename)
            protocol.disconnect()
            self._success(handler, protocol, fileInfo, start_pc)
        except KeyboardInterrupt:
            filetransfer.abort()
            self._fail(handler, protocol, "Aborting transfer", fileInfo, start_pc)
        except FatalError:
            self._fail(handler, protocol, "Too many retries", fileInfo, start_pc)
        except Exception as exc:
            self._fail(handler, protocol, exc, fileInfo, start_pc)
        finally:
            if (protocol):
                protocol.shutdown()
            handler.fire_changed(Phase.Inactive)

    def _success(self, handler, protocol, fileInfo, start_pc):
        self.logger.info("Transfer succeeded")
        handler.success(fileInfo.local_basename, fileInfo.remote_basename, perf_counter() - start_pc)
        if self.settings.get_boolean(Setting.PostTransferGcodeEnable):
            self.bft_logger.info("Sending gcode after transfer: %s" % self.settings.get(Setting.PostTransferGcode))
            protocol.connected = False
            protocol.worker_thread.join()
            protocol.send_ascii_no_wait("\n".join(self.settings.get(Setting.PostTransferGcode)))
        self.bft_logger.info("Done!")
        handler.fire_changed(Phase.CompleteOK, fileInfo.local_path)

    def _fail(self, handler, protocol, error, fileInfo, start_pc):
        protocol.send_ascii("M117 {0}".format(error))
        self.logger.error("Transfer failed: {0}".format(error))
        handler.failure(fileInfo.local_basename, fileInfo.remote_basename, perf_counter() - start_pc, str(error))
        handler.fire_changed(Phase.CompleteFail, fileInfo.local_path)