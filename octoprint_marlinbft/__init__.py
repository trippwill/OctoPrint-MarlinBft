# coding=utf-8
from __future__ import absolute_import, unicode_literals

import os
import threading
import time

import octoprint.plugin
from binproto2 import FatalError, FileTransferProtocol, Protocol
from octoprint.events import Events

from octoprint_marlinbft.utils import EventNames, BftLogger, DialogHandler, DeleteUpload, Setting, Phase

CAP_BINARY_FILE_TRANSFER = "BINARY_FILE_TRANSFER"

class MarlinbftPlugin(octoprint.plugin.StartupPlugin,
                      octoprint.plugin.SettingsPlugin,
                      octoprint.plugin.AssetPlugin,
                      octoprint.plugin.TemplatePlugin,
                      octoprint.plugin.EventHandlerPlugin,
                      octoprint.plugin.SimpleApiPlugin):
        
    def __init__(self):
        self.bft_logger = None
    
    def _fire_phase_changed(self, curr, msg=None):
        self._logger.info("Firing phase change (%s -> %s): %s" % (self._settings.get(Setting.Phase), curr, msg))
        self._event_bus.fire(Events.PLUGIN_MARLINBFT_PHASE_CHANGED, dict(
            prev = self._settings.get(Setting.Phase),
            curr = curr,
            msg  = msg
        ))

    ##~~ StartupPlugin

    def on_after_startup(self):
        self._logger.info("MARLIN BFT MARK II")
        self.bft_logger = BftLogger(self._logger, self._plugin_manager)

    ##~~ SettingsPlugin

    def get_settings_defaults(self):
        return dict(
            accept_extensions          = "bin,cur",
            comm_timeout_ms            = 1000,
            has_capability             = False,
            delete_upload              = DeleteUpload.Never,
            phase                      = Phase.Inactive,
            post_transfer_gcode        = ["M997"],
            post_transfer_gcode_enable = False,
            reconnect                  = True,
            upload_folder              = "marlinbft",
            wait_after_connect_ms      = 0,
            wait_before_reconnect_ms   = 0,
        )

    ##~~ AssetPlugin

    def get_assets(self):
        return dict(
            js=["js/marlinbft.js"],
        )

    ##~~ TemplatePlugin

    def get_template_configs(self):
        return [
            dict(type='settings',
                 name='Marlin Binary File Transfer',
                 custom_bindings=False),
            dict(type='generic',
                 template='marlinbft_dialog.jinja2'),
        ]

    ##~~ EventPlugin

    def on_event(self, event, payload):
        event = event.lower()
        if event in ["disconnecting", "disconnected"] and not self._settings.get(Setting.Phase) in [Phase.Inactive, Phase.CompleteOK, Phase.CompleteFail]:
            self._settings.set(Setting.HasCapability, False)
            self._logger.info("Unsetting capability %s", CAP_BINARY_FILE_TRANSFER)
        elif event == Events.PLUGIN_MARLINBFT_PHASE_CHANGED.lower():
            self._settings.set(Setting.Phase, payload["curr"])
            self._logger.info("Changed phase (%s -> %s): %s" % (payload["prev"], payload["curr"], payload["msg"]))

    ##~~ SimpleApiPlugin

    def get_api_commands(self):
        return dict(
            start_upload=["local_path"],
            change_phase=["curr"]
        )

    def on_api_command(self, command, data):
        def start_upload():
            self._logger.info("API: start_upload")
            self._logger.info(data)
            (_, port, baudrate, profile) = self._printer.get_current_connection()
            self.octo_profile = profile
            self.start_binary_transfer(port, baudrate, data["local_path"], DialogHandler(self._logger, self._event_bus, self._settings))

        def change_phase():
            self._logger.info("API: change_phase")
            self._logger.info(data)
            self._fire_phase_changed(getattr(Phase, data["curr"]))

        def raise_error():
            raise NotImplementedError()

        dict(
            start_upload=start_upload,
            change_phase=change_phase
        ).get(command, raise_error)()
        
    ##~~ capabilites hook

    def on_firmware_capability(self, comm_instance, capability, enabled, already_defined):
        del comm_instance, already_defined
        if capability.lower() == CAP_BINARY_FILE_TRANSFER.lower():
            self._settings.set(Setting.HasCapability, enabled)
            self._logger.info("Setting %s capability to %s" % (CAP_BINARY_FILE_TRANSFER, self._settings.get(Setting.HasCapability)))

    def start_binary_transfer(self, port, baudrate, local_path, handler):
        self._fire_phase_changed(Phase.PreConnect, local_path)
        start_pc = time.perf_counter()

        _, local_basename = os.path.split(local_path)
        root, ext = os.path.splitext(local_basename)
        remote_basename = os.path.basename(root)[:8] + ext[:4]

        disk_path = self._file_manager.path_on_disk("local", local_path)
        self._logger.info("Path on disk '%s'" % disk_path)

        self.bft_logger.info("Starting upload of %s to %s on remote" % (local_path, remote_basename))

        if not self._settings.get(Setting.HasCapability):
            handler.failure(local_basename, remote_basename, time.perf_counter() - start_pc, "The required capability '%s' is not present on the connected printer." % CAP_BINARY_FILE_TRANSFER)
            return None
        self.bft_logger.info("Disconnecting from %s" % port)
        self._printer.disconnect()
            
        def success(protocol):
            self._logger.info("Transfer succeeded")
            handler.success(local_basename, remote_basename, time.perf_counter() - start_pc)
            self.bft_logger.info("Wait for printer to reconnect")	
            if self._settings.get_boolean(Setting.PostTransferGcodeEnable):
                self.bft_logger.info("Sending gcode after transfer")
                protocol.send_ascii("\n".join(self._settings.get(Setting.PostTransferGcode)))

            if self._settings.get_boolean(Setting.Reconnect):
                wait_before_reconnect_ms = self._settings.get_int(Setting.WaitBeforeReconnect)
                self.bft_logger.info("Waiting %sms before reconnecting to printer" % wait_before_reconnect_ms)
                time.sleep(wait_before_reconnect_ms / 1000)
                self._printer.connect(port, baudrate, self.octo_profile)

            if self._settings.get(Setting.DeleteUpload) in [DeleteUpload.OnlyOnSuccess, DeleteUpload.Always]:
                cleanup_file()


        def fail(protocol, error):
            protocol.send_ascii("M117 {0}".format(error))
            self._logger.error("Transfer failed: {0}".format(error))
            handler.failure(local_basename, remote_basename, time.perf_counter() - start_pc, str(error))

            if self._settings.get(Setting.DeleteUpload) in [DeleteUpload.OnlyOnFail, DeleteUpload.Always]:
                cleanup_file()

        def cleanup_file():
            self.bft_logger.info("Cleaning up file")
            self._file_manager.remove_file("local", local_path)

        def process():
            handler.start(local_basename, remote_basename)
            self._logger.info("Starting process thread")
            protocol = Protocol(port, baudrate, 512, self._settings.get_int(Setting.CommTimeout), self.bft_logger)

            try:
                wait_after_connect = self._settings.get_int(Setting.WaitAfterConnect)
                if wait_after_connect > 0:
                    self._logger.info("waiting %sms after protocol connect" % wait_after_connect)
                    time.sleep(wait_after_connect / 1000)

                protocol.send_ascii("M155 S0")
                protocol.send_ascii("M117 Receiving file " + remote_basename + " ...")
                protocol.connect()

                self._fire_phase_changed(Phase.Transfer)

                filetransfer = FileTransferProtocol(protocol, logger=self.bft_logger)
                filetransfer.copy(disk_path, remote_basename, True, False)

                self._fire_phase_changed(Phase.PostTransfer)

                self.bft_logger.info("Please wait for printer to reconnect...")	
                protocol.send_ascii("M117 ...Done! %s" % remote_basename)
                protocol.disconnect()
                success(protocol)
            except KeyboardInterrupt:
                filetransfer.abort()
                fail(protocol, "Aborting transfer")
            except FatalError:
                fail(protocol, "Too many retries")
            except Exception as exc:
                fail(protocol, exc)
            finally:
                protocol.shutdown()
                self.bft_logger.info("Done!")
                self._fire_phase_changed(Phase.Inactive)

        thread = threading.Thread(target=process)
        thread.daemon = True
        thread.start()

        return remote_basename

    ##~~ register_custom_events hook

    def on_register_events(self):
        return EventNames.Registration

    def on_get_extension_tree(self):
        accept = self._settings.get(Setting.AcceptExtensions)
        if accept:
            return dict(
                machinecode=dict(
                    marlinbin=accept.split(sep=",")
                ))

    ##~~ softwareupdate hook

    def get_update_information(self):
        # Define the configuration for your plugin to use with the Software Update
        # Plugin here. See https://docs.octoprint.org/en/master/bundledplugins/softwareupdate.html
        # for details.
        return dict(
            marlinbft=dict(
                displayName="Marlinbft Plugin",
                displayVersion=self._plugin_version,

                # version check: github repository
                type="github_release",
                user="charleswillis3",
                repo="OctoPrint-MarlinBft",
                current=self._plugin_version,

                # update method: pip
                pip="https://github.com/charleswillis3/OctoPrint-MarlinBft/archive/{target_version}.zip"
            )
        )


__plugin_name__ = "Marlin Binary File Transfer: Protocol Mk II"

# Starting with OctoPrint 1.4.0 OctoPrint will also support to run under Python 3 in addition to the deprecated
# Python 2. New plugins should make sure to run under both versions for now. Uncomment one of the following
# compatibility flags according to what Python versions your plugin supports!
#__plugin_pythoncompat__ = ">=2.7,<3" # only python 2
#__plugin_pythoncompat__ = ">=3,<4" # only python 3
__plugin_pythoncompat__ = ">=2.7,<4" # python 2 and 3

def __plugin_load__():
    global __plugin_implementation__
    __plugin_implementation__ = MarlinbftPlugin()

    global __plugin_hooks__
    __plugin_hooks__ = {
        "octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information,
        "octoprint.comm.protocol.firmware.capabilities": __plugin_implementation__.on_firmware_capability,
        "octoprint.events.register_custom_events": __plugin_implementation__.on_register_events,
        "octoprint.filemanager.extension_tree": __plugin_implementation__.on_get_extension_tree,
    }
