
class EventNames:
    _transfer_started  = "transfer_started"
    _transfer_complete = "transfer_complete"
    _transfer_error    = "transfer_error"
    _phase_changed     = "phase_changed"

    Registration = [_transfer_started, _transfer_complete, _transfer_error, _phase_changed]
    

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

class DialogHandler:
    def __init__(self, logger, event_bus, settings):
        self.logger = logger
        self.event_bus = event_bus
        self.settings = settings

    def start(self, local_name, remote_name):
        self.logger.info("DIALOG START %s %s" % (local_name, remote_name))
        self._fire_changed(Phase.Connect)

    def success(self, local_name, remote_name, elapsed):
        self.logger.info("DIALOG_SUCCESS %s %s %s" % (local_name, remote_name, elapsed))
        self._fire_changed(Phase.CompleteOK)

    def failure(self, local_name, remote_name, elapsed, msg):
        self.logger.info("DIALOG_FAILURE %s %s %s" % (local_name, remote_name, elapsed))
        self._fire_changed(Phase.CompleteFail)

    def _fire_changed(self, current, msg=None):
        self.event_bus.fire(Events.PLUGIN_MARLINBFT_PHASE_CHANGED, dict(
            prev = self.settings.get(Setting.Phase),
            curr = current,
            msg  = msg
        ))


class BftLogger:
    def __init__(self, logger, plugin_manager):
        self.logger = logger
        self.plugin_manager = plugin_manager

    def info(self, msg):
        self.logger.info(msg)
        self._push(msg)

    def debug(self, msg):
        self.logger.debug(msg)

    def warn(self, msg):
        self.logger.warn(msg)
        self._push(msg)

    def error(self, msg):
        self.logger.error(msg)
        self._push(msg)

    def _push(self, msg):
        self.plugin_manager.send_plugin_message("marlinbft", str(msg))
