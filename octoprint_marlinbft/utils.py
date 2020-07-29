"""
Marlin BinaryFile Transfer Utilities
"""

from octoprint.events import Events as OEvents

def _resolve_event_name(name):
    return "{0}_{1}".format("PLUGIN_MARLINBFT", name.upper())

class _Names:
    _transfer_started  = "transfer_started"
    _transfer_complete = "transfer_complete"
    _transfer_error    = "transfer_error"
    _phase_changed     = "phase_changed"

class BftEvents:
    TransferStarted  = staticmethod(lambda: getattr(OEvents, _resolve_event_name(_Names._transfer_started)))
    TransferComplete = staticmethod(lambda: getattr(OEvents, _resolve_event_name(_Names._transfer_complete)))
    TransferError    = staticmethod(lambda: getattr(OEvents, _resolve_event_name(_Names._transfer_error)))
    PhaseChanged     = staticmethod(lambda: getattr(OEvents, _resolve_event_name(_Names._phase_changed)))

    Registration = [_Names._transfer_started, _Names._transfer_complete, _Names._transfer_error, _Names._phase_changed]

class Setting:
    AcceptExtensions        = ["accept_extensions"]
    CommTimeout             = ["comm_timeout_ms"]
    HasCapability           = ["has_capability"]
    DeleteUpload            = ["delete_upload"]
    Phase                   = ["phase"]
    PostTransferGcode       = ["post_transfer_gcode"]
    PostTransferGcodeEnable = ["post_transfer_gcode_enable"]
    Reconnect               = ["reconnect"]
    UploadFolder            = ["upload_folder"]
    WaitAfterConnect        = ["wait_after_connect_ms"]
    WaitBeforeReconnect     = ["wait_before_reconnect_ms"]

class SettingsResolver(object):

    override_settings = {}

    def __init__(self, base_settings, logger):
        self.base_settings = base_settings
        self.logger = logger

    def get(self, path):
        def _get(overrides, segments):
            self.logger.debug("Settings Resolver _get")
            self.logger.debug(overrides)
            self.logger.debug(segments)
            if len(segments) == 0:
                return overrides

            return _get(overrides[segments[0]], segments[1:])

        self.logger.debug("Settings Resolver get")
        self.logger.debug(self.override_settings)

        try:
            val = _get(self.override_settings, path)
            self.logger.debug("[SettingsResolver]: value from override_settings %s:" % path)
            self.logger.debug(val)
            return val
        except KeyError:
            self.logger.debug("[SettingsResolver]: key not found in override_settings %s" % path)
            return self.base_settings.get(path)

    def get_int(self, path):
        return int(self.get(path))

    def get_boolean(self, path):
        return bool(self.get(path))

class DeleteUpload:
    Never         = "Never"
    OnlyOnSuccess = "OnlyOnSuccess"
    OnlyOnFail    = "OnlyOnFail"
    Always        = "Always"


class Phase:
    Inactive     = "Inactive"
    Upload       = "Upload"
    PreConnect   = "PreConnect"
    Connect      = "Connect"
    Transfer     = "Transfer"
    PostTransfer = "PostTransfer"
    CompleteOK   = "CompleteOK"
    CompleteFail = "CompleteFail"


from octoprint.events import Events

class BftHandler(object):
    def start(self, local_name, remote_name):
        pass

    def success(self, local_name, remote_name, elapsed):
        pass

    def failure(self, local_name, remote_name, elapsed, msg):
        pass

    def fire_changed(self, current, msg=None):
        pass

class ApiHandler(BftHandler):
    def __init__(self):
        self.output = []

    def start(self, local_name, remote_name):
        self.output.append("Starting transfer of %s as remote %s" % (local_name, remote_name))

    def success(self, local_name, remote_name, elapsed):
        self.output.append("Transfer of %s to remote as %s completed in %s" % (local_name, remote_name, elapsed))

    def failure(self, local_name, remote_name, elapsed, msg):
        self.output.append("Transfer of %s to remote as %s failed in %s with error %s" % (local_name, remote_name, elapsed, str(msg)))

    def fire_changed(self, current, msg=None):
        self.output.append("Starting phase %s (%s)" % (current, str(msg)))

    def __str__(self):
        return "\n".join(self.output)

class DialogHandler(ApiHandler):
    def __init__(self, logger, event_bus, settings):
        self.logger = logger
        self.event_bus = event_bus
        self.settings = settings
        super(ApiHandler,self).__init__()

    def start(self, local_name, remote_name):
        self.logger.info("DIALOG START %s %s" % (local_name, remote_name))
        self.fire_changed(Phase.Connect)
        super(ApiHandler,self).start(local_name, remote_name)

    def success(self, local_name, remote_name, elapsed):
        self.logger.info("DIALOG_SUCCESS %s %s %s" % (local_name, remote_name, elapsed))
        self.fire_changed(Phase.PostTransfer)
        super(ApiHandler,self).success(local_name, remote_name, elapsed)

    def failure(self, local_name, remote_name, elapsed, msg):
        self.logger.info("DIALOG_FAILURE %s %s %s" % (local_name, remote_name, elapsed))
        self.fire_changed(Phase.PostTransfer)
        super(ApiHandler,self).failure(local_name, remote_name, elapsed, msg)

    def fire_changed(self, current, msg=None):
        self.event_bus.fire(BftEvents.PhaseChanged(), dict(
            prev = self.settings.get(Setting.Phase),
            curr = current,
            msg  = msg
        ))
        super(ApiHandler,self).fire_changed(current, msg)

import copy

class BftLogger:
    def __init__(self, logger, plugin_manager, prefix = None):
        self.logger = logger
        self.plugin_manager = plugin_manager
        self.prefix = prefix or "BFT"

    def info(self, msg):
        self.logger.info(self._prefix(msg))
        self._push(msg)

    def debug(self, msg):
        self.logger.debug(self._prefix(msg))

    def warn(self, msg):
        self.logger.warn(self._prefix(msg))
        self._push(msg)

    def error(self, msg):
        self.logger.error(self._prefix(msg))
        self._push(msg)

    def copy(self, prefix = None):
        c = copy.copy(self)
        c.prefix = prefix or self.prefix
        return c

    def _push(self, msg):
        self.plugin_manager.send_plugin_message("marlinbft", str(msg))

    def _prefix(self, msg):
        return "[%s]: %s" % (self.prefix, str(msg))
