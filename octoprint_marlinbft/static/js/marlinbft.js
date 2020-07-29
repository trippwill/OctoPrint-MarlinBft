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
        self.settings    = ko.observable(undefined);

        self.output           = ko.observableArray();
        self.activeHelpText   = ko.observable(undefined);
        self.isSending        = ko.observable(undefined);

        self.postGcode        = ko.pureComputed({
            read: function() {
                return self.settings.post_gcode().join(";");
            },

            write: function(val) {
                self.settings.post_gcode(val.split(";"));
                self.settings_vm.saveData();
            },
        });

        self.canSend = ko.pureComputed(() => self.connection.isOperational() && self.settings.has_capability());

        self.uploadButton    = $("#upload-binary");
        self.marlinbftDialog = $("#marlinbft-dialog");
        self.bftTerminal     = $("#bft-terminal");
        
        self.octoTerminal    = $("#terminal-output");

        self.onBeforeBinding = function() {
            console.log("BeforeBinding: MarlinBFT");
            self.settings = self.settings_vm.settings.plugins.marlinbft;
            self._updateTerminal(false);

            var helpTextElements = $("[data-helptext]");
            var eventBinding = "event: { mouseover: setHelpText.bind($data, $element), mouseout: clearHelpText }";
            helpTextElements.each(function() {
                var currentBinding = $(this).attr("data-bind");
                $(this).attr("data-bind", [eventBinding, currentBinding].join(", "));
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
        }

        self._setFileUpload = function() {
            var url = API_BASEURL + "files/local";

            self.uploadButton.fileupload({
                url: url,
                dataType: "json",
                add:  self._handleUploadAdd,
                done: self._handleUploadDone,
                fail: self._handleUploadFail,
                progress: self._handleUploadProgress
            });
        }

        self._handleUploadAdd = function(e, data) {
            self._updateTerminal(false);
            self.isSending(true);
            data.formData = { path: self.settings.upload_folder() };
            
            console.log("Upload phase: add file to queue");
            console.log(data);
            self._updateTerminal("Starting upload to OctoPrint server");

            if (self.connection.isPrinting()) {
                self._updateTerminal("Confirm disconnect");
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
        }

        self._startUpload = function(data) {
            console.log("Upload phase: start upload to server");
            OctoPrint.simpleApiCommand(pluginid, "change_phase", {"curr": "Upload"});
            data.submit();
        }

        self._handleUploadDone = function(e, data) {
            console.log("Upload phase: done");
            console.log(data);
            self._updateTerminal("Upload to server done");
            self._updateTerminal("Starting transfer to Marlin");

            OctoPrint.connection.getSettings()
                .then(settings => {
                    self.currentPrinter = settings.current;
                    OctoPrint.connection.disconnect().then(_ => {
                        params = {
                            "local_path": data.result.files.local.path,
                            "port": self.currentPrinter.port,
                            "baudrate": self.currentPrinter.baudrate,
                            "handler_type": "dialog"
                        };

                        console.log("Start transfer");
                        console.log(params);

                        OctoPrint.simpleApiCommand(pluginid, "start_transfer", params)
                            .always(resp => {
                                console.log(resp);
                                self._updateTerminal(resp.statusText)
                            });
                    });
                });
        }

        self._handleUploadFail = function(e, data) {
            console.log("Upload phase: fail");
            console.log(data);
            self._updateTerminal("Upload to server failed");
            OctoPrint.simpleApiCommand(pluginid, "change_phase", {"curr": "Inactive"});
        }

        self._handleUploadProgress = function (e, data) {
            self._updateTerminal("UPLOAD PROGRESS: " + parseInt(data.loaded / data.total * 100, 10));
        }

        self.onDataUpdaterPluginMessage = function(plugin, message) {
            if (plugin == pluginid) {
                self._updateTerminal(message);
            }
        }

        self._updateTerminal = function(msg) {
            if (msg) {
                self.output.push(msg);
                self.bftTerminal.scrollTop(self.bftTerminal[0].scrollHeight);
            } else {
                self.output.removeAll();
            }
        }

        self.onEventplugin_marlinbft_phase_changed = function(payload) {
            console.log(payload.prev + " ==> " + payload.curr);
            switch (payload.curr) {
                case "CompleteOK":
                    if (self.settings.reconnect()) {
                        var to = self.settings.wait_before_reconnect_ms();
                        self._updateTerminal("Printer will reconnect in " + to/1000 + "s...");
                        window.setTimeout(
                            self._reconnectPrinter,
                            to
                        );
                    }
                    if (["OnlyOnSuccess", "Always"].includes(self.settings.delete_upload())) {
                        self._cleanupFile(payload.msg);
                    }
                    break;
                case "CompleteFail":
                    if (["OnlyOnFail", "Always"].includes(self.settings.delete_upload())) {
                        self._cleanupFile(payload.msg);
                    }
                    break;
            }
        }

        self._reconnectPrinter = function() {
            OctoPrint.connection.connect(self.currentPrinter);
            self.close();
        }

        self._cleanupFile = function(path) {
            console.log("deleting file: " + path);
            OctoPrint.files.delete("local", path);
        }

        self.show = function() {
            self.clearHelpText();
            self.marlinbftDialog.modal("show");
        }

        self.close = function() {
            self.marlinbftDialog.modal("hide");
        }

        self.settingsShow = function() {
            self.settings_vm.show("settings_plugin_marlinbft");
        }

        self.togglePostTransferGcode = function() {
            self.settings.post_transfer_gcode_enable(
                !self.settings.post_transfer_gcode_enable()
            );

            self.settings_vm.saveData();
        }

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
            var default_helptext = "Set options, then select 'Upload to SD' to begin.";

            if (!self.connection.isOperational()) {
                default_helptext = "Printer must be connected to enable file transfer.";
            } else if (!self.settings.has_capability()) {
                default_helptext = "Connected printer must have (and report) the BINARY_FILE_TRANSFER capability.";
            }

            self.activeHelpText(default_helptext);
        }
    }

    OCTOPRINT_VIEWMODELS.push({
        construct: MarlinbftViewModel,
        dependencies: ["settingsViewModel", "loginStateViewModel", "connectionViewModel", "accessViewModel"],
        elements: ["#marlinbft-dialog", "#navbar_plugin_marlinbft"]
    });
});
