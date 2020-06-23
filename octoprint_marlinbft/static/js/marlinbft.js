/*
 * View model for OctoPrint-MarlinBft
 *
 * Author: Charles Willis
 * License: MIT
 */
$(function() {
    function MarlinbftViewModel(parameters) {
        var self = this;
        var pluginid = "marlinbft";

        self.settings_vm = parameters[0];
        self.loginState  = parameters[1];
        self.connection  = parameters[2];
        self.access      = parameters[3];
        self.settings    = undefined;

        self.output           = ko.observableArray();
        self.activeHelpText   = ko.observable(undefined);
        self.isSending        = ko.observable(undefined);
        self.selectedPort     = ko.observable(undefined);
        self.selectedBaudrate = ko.observable(undefined);

        self.postGcode        = ko.pureComputed({
            read: function() {
                var self = this;
                return self.settings.post_gcode().join(";");
            },

            write: function(val) {
                var self = this;
                self.settings.post_gcode(val.split(";"));
                self.settings_vm.saveData();
            },

            owner: self
        });

        self.uploadButton    = $("#upload-binary");
        self.marlinbftDialog = $("#marlinbft-dialog");
        self.octoTerminal    = $("#terminal-output");
        self.bftTerminal     = $("#bft-terminal");

        self.availableDelete   = [
            "Never",
            "OnlyOnSuccess",
            "OnlyOnFail",
            "Always"
        ]

        self.onBeforeBinding = function() {
            self.settings = self.settings_vm.settings.plugins.marlinbft;

            console.log("BeforeBinding: MarlinBFT");
            self.output.removeAll();

            var helpTextElements = $("[data-helptext]");
            var eventBinding = "event: { mouseover: setHelpText.bind($data, $element), mouseout: clearHelpText }";
            helpTextElements.each(function() {
                var currentBinding = $(this).attr("data-bind");
                $(this).attr("data-bind", [eventBinding, currentBinding].join(", "));
            });
        };

        self._setFileUpload = function() {
            var url = API_BASEURL + "files/local";

            self.uploadButton.fileupload({
                url: url,
                dataType: "json",
                add:  self._handleUploadAdd,
                done: self._handleUploadDone,
                fail: self._handleUploadFail,
            });
        }

        self.onAfterBinding = function() {
            var props = ["background-color", "color"];
            props.forEach(function(prop) {
                self.bftTerminal.css(prop,
                    self.octoTerminal.css(prop));
            });

            self._setFileUpload();
            self.clearHelpText();
            self.isSending(false);
        };

        self._handleUploadAdd = function(e, data) {
            self.isSending(true);
            data.formData = { path: self.settings.upload_folder() };
            
            console.log("Upload phase: add file to queue");
            console.log(data);
            self.output.push("Starting upload to OctoPrint server");

            if (self.connection.isPrinting()) {
                self.output.push("Confirm disconnect");
                showSelectionDialog({
                    title: "Confirm disconnect",
                    message: "<p><strong>You are about to disconnect from the printer"
                        + " while a print is in progress.</strong></p>"
                        + "<p>Disconnecting while a print is in progress will prevent the print from completing.</p>",
                    selections: [
                        "Cancel",
                        "Continue"
                    ],
                    maycancel: true,
                    onselect: function(idx) {
                        console.log("Selection Dialog Result: " + idx);
                        switch (idx) {
                            case 0:
                                console.log("Cancelling");
                                return false;
                            case 1:
                                console.log("Continuing");
                                self.shouldReconnect = false;
                                break;
                        }

                        self._startUpload(data);
                    },
                    onclose: function() {
                        return false;
                    }
                });
            } else {
                self._startUpload(data);
            }
        };

        self._startUpload = function(data) {
            console.log("Upload phase: start upload to server");
            OctoPrint.simpleApiCommand(pluginid, "change_phase", {"curr": "Upload"});
            data.submit();
        };

        self._handleUploadDone = function(e, data) {
            console.log("Upload phase: done");
            console.log(data);
            self.output.push("Upload to server done");
            self.output.push("Starting transfer to Marlin");

            OctoPrint.simpleApiCommand(pluginid, "start_upload", {
                "local_path": data.result.files.local.path
            });
        };

        self._handleUploadFail = function(e, data) {
            console.log("Upload phase: fail");
            console.log(data);
            self.output.push("Upload to server failed");
        };

        self.onUserPermissionsChanged = 
        self.onUserLoggedIn = 
        self.onUserLoggedOut = 
        self.onEventSettingsUpdated = 
        self.onEventConnected = 
        self.onEventDisconnected = function() {
            self.refreshConnection();
        };

        self.onDataUpdaterPluginMessage = function(plugin, message) {
            if (plugin == pluginid) {
                self.output.push(message);
                self.bftTerminal.scrollTop(self.bftTerminal[0].scrollHeight);
            }
        };

        self.onEventplugin_marlinbft_transfer_started = function(payload) {
            console.log("Transfer phase: start");
        };

        self.onEventplugin_marlinbft_transfer_complete = function(payload) {
            console.log("Transfer phase: complete");
        };

        self.onEventplugin_marlinbft_transfer_error = function(payload) {
            console.log("Transfer phase: error");
        };

        self.onEventplugin_marlinbft_phase_changed = function(payload) {
            console.log(payload.prev + " ==> " + payload.curr);
        }

        self.show = function() {
            self.refreshConnection();
            self.marlinbftDialog.modal("show");
        };

        self.close = function() {
            self.marlinbftDialog.modal("hide");
        };

        self.settingsShow = function() {
            self.settings_vm.show("settings_plugin_marlinbft");
        };

        self.refreshConnection = function() {
            if(!self.loginState.hasPermission(self.access.permissions.CONNECTION)) {
                return;
            }

            OctoPrint.connection.getSettings()
                .done(self.fromGetSettings);
        };

        self.fromGetSettings = function(resp) {
            self.currentOctoPort = resp.current.port;
            self.currentOctoBaud = resp.current.baudrates;
        };

        self.togglePostTransferGcode = function() {
            self.settings.post_transfer_gcode_enable(
                !self.settings.post_transfer_gcode_enable()
            );

            self.settings_vm.saveData();
        };

        self.toggleReconnect = function() {
            self.settings.reconnect(
                !self.settings.reconnect()
            );

            self.settings_vm.saveData();
        }

        self.setHelpText = function(element) {
            self.activeHelpText(element.dataset.helptext);
        }

        self.clearHelpText = function() {
            var default_helptext = "Set options, then select 'Upload to SD' to begin. Printer must be connected to select file.";
            self.activeHelpText(default_helptext);
        }
    }

    OCTOPRINT_VIEWMODELS.push({
        construct: MarlinbftViewModel,
        dependencies: ["settingsViewModel", "loginStateViewModel", "connectionViewModel", "accessViewModel"],
        elements: ["#marlinbft-dialog", "#navbar_plugin_marlinbft"]
    });
});
