# coding=utf-8

"""
Marlin Binary File Transfer Module
"""
from __future__ import absolute_import, unicode_literals

import os
import threading
import time

import flask
import octoprint.plugin
from binproto2 import FatalError, FileTransferProtocol, Protocol
from octoprint.events import Events

from octoprint_marlinbft.utils import BftLogger, DialogHandler, BftHandler, ApiHandler
from octoprint_marlinbft.utils import DeleteUpload, Setting, Phase, BftEvents

from octoprint_marlinbft.transfer import Process

CAP_BINARY_FILE_TRANSFER = "BINARY_FILE_TRANSFER"

"""
Marlin Binary File Transfer Plugin
"""
class MarlinbftPlugin(octoprint.plugin.StartupPlugin,
                      octoprint.plugin.SettingsPlugin,
                      octoprint.plugin.AssetPlugin,
                      octoprint.plugin.TemplatePlugin,
                      octoprint.plugin.EventHandlerPlugin,
                      octoprint.plugin.SimpleApiPlugin):

    transfer_process = None
        
    def __init__(self):
        self.bft_logger = None
   
    ##~~ StartupPlugin

    def on_after_startup(self):
        self._logger.info("MARLIN BFT MARK II")
        self.bft_logger = BftLogger(self._logger, self._plugin_manager)
        self._settings.set(Setting.HasCapability, False)

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
        if event in ["disconnecting", "disconnected"]:
            self._settings.set(Setting.HasCapability, False)
            self._logger.info("Unsetting capability %s", CAP_BINARY_FILE_TRANSFER)
        elif event == BftEvents.PhaseChanged().lower():
            self._settings.set(Setting.Phase, payload["curr"])
            self._logger.info("Changed phase (%s -> %s): %s" % (payload["prev"], payload["curr"], payload["msg"]))

    ##~~ SimpleApiPlugin

    def get_api_commands(self):
        return dict(
            start_transfer=["local_path", "port", "baudrate"],
            change_phase=["curr"]
        )

    def on_api_command(self, command, data):
        handlers = dict(
            dialog=lambda : DialogHandler(self._logger, self._event_bus, self._settings),
            api=lambda : ApiHandler()
        )

        def _start_transfer():
            self._logger.info("API: start_transfer")
            self._logger.info(data)
            handler = handlers.get(data["handler_type"], lambda: BftHandler())()
            remote_name = self._start_binary_transfer(handler=handler, **data)
            return flask.make_response(remote_name, 200)

        def _change_phase():
            self._logger.info("API: change_phase")
            self._logger.info(data)
            self._fire_phase_changed(getattr(Phase, data["curr"]))

        def raise_error():
            raise NotImplementedError()

        return dict(
            start_transfer=_start_transfer,
            change_phase=_change_phase
        ).get(command, raise_error)()
        
    def _start_binary_transfer(self, handler, port, baudrate, local_path, **data):
        self._logger.info(data)
        handler.fire_changed(Phase.PreConnect, local_path)

        _, local_basename = os.path.split(local_path)
        root, ext = os.path.splitext(local_basename)
        remote_basename = os.path.basename(root)[:8] + ext[:4]

        disk_path = self._file_manager.path_on_disk("local", local_path)
        self._logger.info("Path on disk '%s'" % disk_path)
        self.bft_logger.info("Starting transfer of %s to %s on remote" % (local_path, remote_basename))

        if not MarlinbftPlugin.transfer_process:
            MarlinbftPlugin.transfer_process = Process(self._logger, self._settings, self.bft_logger)
        
        thread = threading.Thread(target=MarlinbftPlugin.transfer_process.start, args=(
            handler,
            local_basename,
            remote_basename,
            disk_path,
            port,
            baudrate,
            local_path
        ), kwargs=data)

        thread.daemon = True
        thread.start()

        return remote_basename

    def _fire_phase_changed(self, curr, msg=None):
        self._logger.info(
            "Firing phase change (%s -> %s): %s" % (self._settings.get(Setting.Phase), curr, msg))
        self._event_bus.fire(BftEvents.PhaseChanged(), dict(
            prev = self._settings.get(Setting.Phase),
            curr = curr,
            msg  = msg
        ))

    ##~~ capabilites hook

    def on_firmware_capability(self, comm_instance, capability, enabled, already_defined):
        del comm_instance, already_defined
        if capability.lower() == CAP_BINARY_FILE_TRANSFER.lower():
            self._settings.set(Setting.HasCapability, enabled)
            self._logger.info("Setting %s capability to %s" % (CAP_BINARY_FILE_TRANSFER, self._settings.get(Setting.HasCapability)))

    ##~~ register_custom_events hook

    def on_register_events(self):
        return BftEvents.Registration

    ##~~ extension_tree hook

    def on_get_extension_tree(self):
        accept = self._settings.get(Setting.AcceptExtensions)
        if accept:
            return dict(
                machinecode=dict(
                    marlinbin=accept.split(",")
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
