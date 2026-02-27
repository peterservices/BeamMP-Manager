const homeButton = document.getElementById("homeButton");
const modsButton = document.getElementById("modsButton");
const logsButton = document.getElementById("logsButton");
const configButton = document.getElementById("configButton");

const homePage = document.getElementById("homePage");
const modsPage = document.getElementById("modsPage");
const logsPage = document.getElementById("logsPage");
const configPage = document.getElementById("configPage");

const errorToast = document.getElementById("errorToast");
const infoToast = document.getElementById("infoToast");
const toastContainer = document.querySelector(".toast-container");

const uploadModal = document.getElementById("uploadModal");
const clearModal = document.getElementById("clearModal");
const kickModal = document.getElementById("kickModal");
const messageModal = document.getElementById("messageModal");
const deleteModal = document.getElementById("deleteModal");
const restartModal = document.getElementById("restartModal");
const reloadModal = document.getElementById("reloadModal");
const updateModal = document.getElementById("updateModal");
const settingModal = document.getElementById("settingModal");

const uploadModalButton = document.getElementById("uploadModalButton");
const kickModalLabel = document.getElementById("kickModalLabel");
const deleteModalLabel = document.getElementById("deleteModalLabel");

const formFilename = document.getElementById("formFilename");
const formFile = document.getElementById("formFile");
const kickReason = document.getElementById("kickReason");
const message = document.getElementById("message");
const settingForm = document.getElementById("settingForm");

const enabledModsLabel = document.getElementById("enabledModsLabel");
const disabledModsLabel = document.getElementById("disabledModsLabel");

const players = document.querySelector("#players");
const serverStatus = document.querySelector("#serverStatus");
const enabledMods = document.querySelector("#enabledMods");
const disabledMods = document.querySelector("#disabledMods");
const playerLogs = document.querySelector("#playerLogs");
const chatLogs = document.querySelector("#chatLogs");
const serverVersion = document.querySelector("#serverVersion");

const server_data = {};
const server_settings = {};

const connection = new WebSocket("ws");

const uploadModalBS = bootstrap.Modal.getOrCreateInstance(uploadModal);
const clearModalBS = bootstrap.Modal.getOrCreateInstance(clearModal);
const kickModalBS = bootstrap.Modal.getOrCreateInstance(kickModal);
const messageModalBS = bootstrap.Modal.getOrCreateInstance(messageModal);
const deleteModalBS = bootstrap.Modal.getOrCreateInstance(deleteModal);
const restartModalBS = bootstrap.Modal.getOrCreateInstance(restartModal);
const reloadModalBS = bootstrap.Modal.getOrCreateInstance(reloadModal);
const updateModalBS = bootstrap.Modal.getOrCreateInstance(updateModal);
const settingModalBS = bootstrap.Modal.getOrCreateInstance(settingModal);

const enabledModsTooltip = new bootstrap.Tooltip(enabledModsLabel);
const disabledModsTooltip = new bootstrap.Tooltip(disabledModsLabel);

let uploadController = null;

let connected = false;

// Ping the server every minute to keep the websocket open
const pingServer = setInterval(() => {
    connection.send(JSON.stringify({"type": "ping"}));
}, 60000);

function showToast(type, text) {
    // Select the type of toast to copy
    let referenceToast;
    if (type == "error") {
        referenceToast = errorToast;
    } else if (type == "info") {
        referenceToast = infoToast;
    } else {
        return;
    }

    // Create a copy of the reference toast
    const toast = document.createElement("div");
    toast.className = referenceToast.className;
    toast.role = referenceToast.role;
    toast.ariaLive = referenceToast.ariaLive;
    toast.ariaAtomic = referenceToast.ariaAtomic;
    toast.setAttribute("data-bs-delay", referenceToast.getAttribute("data-bs-delay"));
    
    const toastFlex = document.createElement("div");
    toastFlex.className = referenceToast.children[0].className;
    toast.appendChild(toastFlex);

    const toastBody = document.createElement("div");
    toastBody.className = referenceToast.children[0].children[0].className;
    toastBody.innerHTML = ((text !== null) ? text : referenceToast.children[0].children[0].innerHTML);
    toastFlex.appendChild(toastBody);

    const toastButton = document.createElement("button");
    toastButton.className = referenceToast.children[0].children[1].className;
    toastButton.type = referenceToast.children[0].children[1].type;
    toastButton.setAttribute("data-bs-dismiss", referenceToast.children[0].children[1].getAttribute("data-bs-dismiss"));
    toastButton.ariaLabel = referenceToast.children[0].children[1].ariaLabel;
    toastFlex.appendChild(toastButton);

    // Show the toast
    toastContainer.appendChild(toast);
    const toastBootstrap = bootstrap.Toast.getOrCreateInstance(toast);
    toastBootstrap.show();

    // Delete the toast after it is closed
    toast.addEventListener("hidden.bs.toast", () => {
        toast.remove();
    });
}

function showUploadModal() {
    uploadModalButton.innerHTML = "Upload";
    uploadModalButton.disabled = false;
    formFilename.value = null;
    formFile.value = null;
    uploadModalBS.show();
}

function showClearModal() {
    clearModalBS.show();
}

function showKickModal(playerName) {
    kickModalLabel.innerHTML = "Kick " + playerName;
    kickReason.value = null;
    kickModalBS.show();
}

function showMessageModal() {
    message.value = null;
    messageModalBS.show();
}

function showDeleteModal(modName) {
    deleteModalLabel.innerHTML = "Delete " + modName;
    deleteModalBS.show();
}

function showRestartModal() {
    restartModalBS.show();
}

function showReloadModal() {
    if (!uploadModal.ariaHidden) {
        uploadModalBS.hide();
    }
    if (!clearModal.ariaHidden) {
        clearModalBS.hide();
    }
    if (!kickModal.ariaHidden) {
        kickModalBS.hide();
    }
    if (!messageModal.ariaHidden) {
        messageModalBS.hide();
    }
    if (!deleteModal.ariaHidden) {
        deleteModalBS.hide();
    }
    if (!restartModal.ariaHidden) {
        restartModalBS.hide();
    }
    if (!updateModal.ariaHidden) {
        updateModalBS.hide();
    }
    if (!settingModal.ariaHidden) {
        settingModalBS.hide();
    }
    reloadModalBS.show();
}

function showSettingModal() {
    // Delete previous form inputs
    const settingLength = settingForm.children.length;
    for (let i = 0; i < settingLength; i++) {
        settingForm.children[0].remove();
    }

    for (let key in server_settings) {
        const value = server_settings[key];
        switch (typeof value) {
            case "boolean":
                const bool_div = document.createElement("div");
                bool_div.className = "form-check form-switch";
                bool_div.style = "margin-bottom: 10px;";

                const bool_label = document.createElement("label");
                bool_label.for = key;
                bool_label.className = "form-check-label";
                bool_label.innerHTML = key;

                const bool_input = document.createElement("input");
                bool_input.type = "checkbox";
                bool_input.name = "switch";
                bool_input.id = key;
                bool_input.className = "form-check-input";
                bool_input.switch = true;
                bool_input.checked = value;
                bool_input.changed = false;

                bool_input.onchange = () => {
                    bool_input.changed = bool_input.checked != value;
                    bool_label.style = ((bool_input.changed) ? "font-style: italic;" : "");
                };

                bool_div.appendChild(bool_label);
                bool_div.appendChild(bool_input);
                settingForm.appendChild(bool_div);
                break;
            case "number":
                const num_label = document.createElement("label");
                num_label.for = key;
                num_label.className = "form-label";
                num_label.innerHTML = key;

                const num_input = document.createElement("input");
                num_input.type = "number";
                num_input.id = key;
                num_input.className = "form-control";
                num_input.style = "margin-bottom: 10px;";
                num_input.value = value;
                num_input.changed = false;

                num_input.onchange = () => {
                    num_input.changed = num_input.value != value;
                    num_label.style = ((num_input.changed) ? "font-style: italic;" : "");
                };

                settingForm.appendChild(num_label);
                settingForm.appendChild(num_input);
                break;
            case "string":
                if (key == "Map") { // Create a dropdown/text input combination to select maps
                    const map_label = document.createElement("label");
                    map_label.id = key + "label";
                    map_label.for = key;
                    map_label.className = "form-label";
                    map_label.innerHTML = key;

                    const map_div = document.createElement("div");
                    map_div.className = "input-group";
                    map_div.style = "margin-bottom: 10px;";

                    const map_button1 = document.createElement("button");
                    map_button1.className = "btn btn-outline-secondary dropdown-toggle";
                    map_button1.type = "button";
                    map_button1.setAttribute("data-bs-toggle", "dropdown");
                    map_button1.ariaExpanded = "false";
                    map_button1.innerHTML = "Input Mode";
                    const map_button2 = document.createElement("button");
                    map_button2.id = key + "button2";
                    map_button2.className = "btn btn-outline-secondary dropdown-toggle";
                    map_button2.type = "button";
                    map_button2.setAttribute("data-bs-toggle", "dropdown");
                    map_button2.ariaExpanded = "false";
                    map_button2.innerHTML = value;

                    const map_input = document.createElement("input");
                    map_input.type = "text";
                    map_input.id = key;
                    map_input.name = "level";
                    map_input.className = "form-control";
                    map_input.value = value;
                    map_input.changed = false;
                    map_input.hidden = true;

                    map_input.onchange = () => {
                        map_input.changed = map_input.value != value;
                        map_button2.innerHTML = map_input.value;
                        map_label.style = ((map_input.changed) ? "font-style: italic;" : "");
                    };

                    const map_dropdown1 = document.createElement("ul");
                    map_dropdown1.className = "dropdown-menu";
                    const map_dropdown2 = document.createElement("ul");
                    map_dropdown2.className = "dropdown-menu";
                    map_dropdown2.id = key + "dropdown";

                    const map_dropdown_button = document.createElement("a");
                    map_dropdown_button.className = "dropdown-item";
                    map_dropdown_button.href = "#";
                    map_dropdown_button.innerHTML = "Autofill";
                    const map_dropdown_mode = document.createElement("li");
                    map_dropdown_mode.appendChild(map_dropdown_button);
                    map_dropdown_button.onclick = () => {
                        map_input.hidden = true;
                        map_button2.hidden = false;
                    };
                    const map_manual_button = document.createElement("a");
                    map_manual_button.className = "dropdown-item";
                    map_manual_button.href = "#";
                    map_manual_button.innerHTML = "Manual";
                    const map_manual_mode = document.createElement("li");
                    map_manual_mode.appendChild(map_manual_button);
                    map_manual_button.onclick = () => {
                        map_input.hidden = false;
                        map_button2.hidden = true;
                    };

                    map_dropdown1.appendChild(map_dropdown_mode);
                    map_dropdown1.appendChild(map_manual_mode);

                    // Add the maps to the dropdown
                    refreshMapDropdown(map_input, map_label, map_button2, map_dropdown2);

                    map_div.appendChild(map_button1);
                    map_div.appendChild(map_dropdown1);
                    map_div.appendChild(map_input);
                    map_div.appendChild(map_button2);
                    map_div.appendChild(map_dropdown2);
                    settingForm.appendChild(map_label);
                    settingForm.appendChild(map_div);
                } else {
                    const str_label = document.createElement("label");
                    str_label.for = key;
                    str_label.className = "form-label";
                    str_label.innerHTML = key;

                    const str_input = document.createElement("input");
                    str_input.type = "text";
                    str_input.id = key;
                    str_input.className = "form-control";
                    str_input.style = "margin-bottom: 10px;";
                    str_input.value = value;
                    str_input.changed = false;

                    str_input.onchange = () => {
                        str_input.changed = str_input.value != value;
                        str_label.style = ((str_input.changed) ? "font-style: italic;" : "");
                    };

                    settingForm.appendChild(str_label);
                    settingForm.appendChild(str_input);
                }
                break;
        }
    }

    settingModalBS.show();
}

function showUpdateModal() {
    const modalTitle = document.getElementById("updateModalLabel");
    const modalContent = document.getElementById("updateModalContent");
    refreshUpdateModal(modalTitle, modalContent);

    updateModalBS.show();
}

function formatBytes(bytes) {
    const kibibytes = bytes / (1024);
    if (kibibytes < 1) {
        return String(bytes) + " B";
    }

    const mebibytes = bytes / (1024 * 1024);
    if (mebibytes < 1) {
        return String(Math.round(kibibytes * 100) / 100) + " KiB";
    }

    const gibibytes = bytes / (1024 * 1024 * 1024);
    if (gibibytes < 1) {
        return String(Math.round(mebibytes * 100) / 100) + " MiB";
    } else {
        return String(Math.round(gibibytes * 100) / 100) + " GiB";
    }
}

function createModDiv(type, modName, filesize) {
    const mod = document.createElement("div");
    mod.className = "d-flex justify-content-between";

    const heading = document.createElement("h4");
    heading.className = "text-truncate";
    heading.style = "flex-grow: 1; overflow: hidden; white-space: nowrap; padding-bottom: 1%; padding-top: 1%;";
    heading.innerHTML = modName;
    heading.setAttribute("data-bs-toggle", "tooltip");
    heading.setAttribute("data-bs-title", modName);
    new bootstrap.Tooltip(heading);
    mod.appendChild(heading);

    const div = document.createElement("div");
    div.style = "flex-shrink: 0;";
    mod.appendChild(div);

    const aDownload = document.createElement("a");
    aDownload.id = modName + "-download";
    aDownload.href = "mods/" + modName;
    aDownload.download = modName;
    aDownload.style = "text-decoration: none;";
    aDownload.setAttribute("data-bs-toggle", "tooltip");
    const size = formatBytes(filesize);
    aDownload.setAttribute("data-bs-title", "Download (" + size + ")");
    new bootstrap.Tooltip(aDownload);
    div.appendChild(aDownload);

    div.appendChild(document.createTextNode(" "));

    const aButton = document.createElement("a");
    aButton.id = modName + "-button";
    aButton.href = "#";
    div.appendChild(aButton);

    const download = document.createElement("button");
    download.type = "button";
    download.className = "btn " + ((type == "enabled") ? "disable-button" : "enable-button");
    aDownload.appendChild(download);

    const image = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    image.setAttribute("width", "16");
    image.setAttribute("height", "16");
    image.setAttribute("fill", "currentColor");
    image.classList.add("bi", "bi-download");
    image.setAttribute("viewBox", "0 0 16 16");
    download.appendChild(image);
    
    const path1 = document.createElementNS(image.namespaceURI, "path");
    path1.setAttributeNS(null, "d", "M.5 9.9a.5.5 0 0 1 .5.5v2.5a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-2.5a.5.5 0 0 1 1 0v2.5a2 2 0 0 1-2 2H2a2 2 0 0 1-2-2v-2.5a.5.5 0 0 1 .5-.5");
    image.appendChild(path1);

    const path2 = document.createElementNS(image.namespaceURI, "path");
    path2.setAttributeNS(null, "d", "M7.646 11.854a.5.5 0 0 0 .708 0l3-3a.5.5 0 0 0-.708-.708L8.5 10.293V1.5a.5.5 0 0 0-1 0v8.793L5.354 8.146a.5.5 0 1 0-.708.708z");
    image.appendChild(path2);

    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn " + ((type == "enabled") ? "disable-button" : "enable-button");
    button.innerHTML = ((type == "enabled") ? "Disable" : "Enable");
    aButton.appendChild(button);

    if (type == "disabled") {
        div.appendChild(document.createTextNode(" "));

        const aDeleteButton = document.createElement("a");
        aDeleteButton.id = modName + "-delete-button";
        aDeleteButton.href = "#";
        div.appendChild(aDeleteButton);

        const deleteButton = document.createElement("button");
        deleteButton.type = "button";
        deleteButton.className = "btn delete-button";
        aDeleteButton.appendChild(deleteButton);

        const deleteImage = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        deleteImage.setAttribute("width", "16");
        deleteImage.setAttribute("height", "16");
        deleteImage.setAttribute("fill", "currentColor");
        deleteImage.classList.add("bi", "bi-download");
        deleteImage.setAttribute("viewBox", "0 0 16 16");
        deleteButton.appendChild(deleteImage);

        const deletePath1 = document.createElementNS(deleteImage.namespaceURI, "path");
        deletePath1.setAttributeNS(null, "d", "M5.5 5.5A.5.5 0 0 1 6 6v6a.5.5 0 0 1-1 0V6a.5.5 0 0 1 .5-.5m2.5 0a.5.5 0 0 1 .5.5v6a.5.5 0 0 1-1 0V6a.5.5 0 0 1 .5-.5m3 .5a.5.5 0 0 0-1 0v6a.5.5 0 0 0 1 0z");
        deleteImage.appendChild(deletePath1);

        const deletePath2 = document.createElementNS(deleteImage.namespaceURI, "path");
        deletePath2.setAttributeNS(null, "d", "M14.5 3a1 1 0 0 1-1 1H13v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V4h-.5a1 1 0 0 1-1-1V2a1 1 0 0 1 1-1H6a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1h3.5a1 1 0 0 1 1 1zM4.118 4 4 4.059V13a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1V4.059L11.882 4zM2.5 3h11V2h-11z");
        deleteImage.appendChild(deletePath2);
    }

    return mod;
}

function createPlayerDiv(playerName) {
    const player = document.createElement("div");
    player.className = "d-flex justify-content-between";

    const heading = document.createElement("h4");
    heading.className = "text-truncate";
    heading.style = "flex-grow: 1; overflow: hidden; white-space: nowrap; padding-bottom: 1%; padding-top: 1%;";
    heading.innerHTML = playerName;
    heading.setAttribute("data-bs-toggle", "tooltip");
    heading.setAttribute("data-bs-title", playerName);
    new bootstrap.Tooltip(heading);
    player.appendChild(heading);

    const div = document.createElement("div");
    div.style = "flex-shrink: 0;";
    player.appendChild(div);

    const aButton = document.createElement("a");
    aButton.id = playerName + "-button";
    aButton.href = "#";
    div.appendChild(aButton);

    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn kick-button";
    button.innerHTML = "Kick";
    aButton.appendChild(button);

    return player;
}

function createLogDiv(content, timestamp = null, tooltipContent = null, logType = "standard") {
    if (tooltipContent === null) {
        tooltipContent = content;
    }
    if (timestamp === null) {
        timestamp = "";
    }
    timestamp = timestamp + " ";

    const log = document.createElement("div");
    log.className = "d-flex justify-content-between";

    let heading;
    let hr1;
    let hr2;
    if (logType == "standard") {
        heading = document.createElement("h4");
        heading.style = "flex-grow: 1; overflow: hidden; white-space: nowrap; padding-bottom: 1%; padding-top: 1%;";
    } else if (logType == "divider") {
        heading = document.createElement("h6");
        heading.style = "overflow: hidden; white-space: nowrap; padding-bottom: 1%; padding-top: 1%; color: #999999;";
        hr1 = document.createElement("hr");
        hr1.style = "flex: 1; margin-left: 15px; margin-right: 15px;";
        hr2 = document.createElement("hr");
        hr2.style = "flex: 1; margin-left: 15px; margin-right: 15px;";
    } else {
        throw Error("Expected logType of value 'standard' or 'divider', got '" + logType + "'");
    }
    heading.className = "text-truncate";
    heading.innerHTML = content;
    heading.setAttribute("data-bs-toggle", "tooltip");
    heading.setAttribute("data-bs-title", timestamp + tooltipContent);
    new bootstrap.Tooltip(heading);
    if (hr1 != null) {
        log.append(hr1);
    }
    log.appendChild(heading);
    if (hr2 != null) {
        log.append(hr2);
    }

    const div = document.createElement("div");
    div.style = "flex-shrink: 0;";
    log.appendChild(div);

    return log;
}

function createUpdateDiv(file) {
    const update = document.createElement("div");
    update.className = "d-flex justify-content-between";

    const heading = document.createElement("h6");
    heading.className = "text-truncate";
    heading.style = "flex-grow: 1; overflow: hidden; white-space: nowrap; padding-bottom: 1%; padding-top: 1%;";
    heading.innerHTML = "OS: " + file["platform"] + ", Arch: " + file["architecture"];
    heading.setAttribute("data-bs-toggle", "tooltip");
    const size = formatBytes(file["size"]);
    heading.setAttribute("data-bs-title", "BeamMP-Server." + file["platform"] + "." + file["architecture"] + " (" + size + ")");
    new bootstrap.Tooltip(heading);
    update.appendChild(heading);

    const div = document.createElement("div");
    div.style = "flex-shrink: 0;";
    update.appendChild(div);

    const aButton = document.createElement("a");
    aButton.id = file["platform"] + "." + file["architecture"] + "-update";
    aButton.href = "#";
    div.appendChild(aButton);

    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn enable-button";
    button.innerHTML = "Update";
    aButton.appendChild(button);

    return update;
}

function refreshMods(mods) {
    // Remove old mods
    const enabledLength = enabledMods.children.length;
    for (let i = 0; i < enabledLength; i++) {
        enabledMods.children[0].remove();
    }
    const disabledLength = disabledMods.children.length;
    for (let i = 0; i < disabledLength; i++) {
        disabledMods.children[0].remove();
    }

    // Add mods
    let total_enabled = 0;
    let total_disabled = 0;
    let enabled_bytes = 0;
    let disabled_bytes = 0;
    for (let key in mods) {
        if (mods[key]["enabled"]) {
            total_enabled++;
            enabled_bytes += mods[key]["filesize"];
            const mod = createModDiv("enabled", key, mods[key]["filesize"]);
            mod.style = "margin-top: 2%;";
            enabledMods.appendChild(mod);
            const disableButton = document.getElementById(key + "-button");
            disableButton.addEventListener("click", () => {
                disableButton.className = "disabled";
                disableButton.children[0].disabled = true;
                connection.send(JSON.stringify({"type": "disable", "disable": key}));
            });
        } else {
            total_disabled++;
            disabled_bytes += mods[key]["filesize"];
            const mod = createModDiv("disabled", key, mods[key]["filesize"]);
            mod.style = "margin-top: 2%;";
            disabledMods.appendChild(mod);
            const enableButton = document.getElementById(key + "-button");
            enableButton.addEventListener("click", () => {
                enableButton.className = "disabled";
                enableButton.children[0].disabled = true;
                connection.send(JSON.stringify({"type": "enable", "enable": key}));
            });
            const deleteButton = document.getElementById(key + "-delete-button");
            deleteButton.addEventListener("click", () => {
                showDeleteModal(key);
            });
        }
    }
    enabledModsTooltip.setContent({".tooltip-inner": String(total_enabled) + " (" + formatBytes(enabled_bytes) + ")"});
    disabledModsTooltip.setContent({".tooltip-inner": String(total_disabled) + " (" + formatBytes(disabled_bytes) + ")"});
}

function refreshPlayers(playerList) {
    // Remove old players
    const playersLength = players.children.length;
    for (let i = 0; i < playersLength; i++) {
        players.children[0].remove();
    }

    // Add players
    for (let id in playerList) {
        const player = createPlayerDiv(playerList[id]);
        player.style = "margin-top: 2%;";
        players.appendChild(player);
        const kickButton = document.getElementById(playerList[id] + "-button");
        kickButton.addEventListener("click", () => {
            showKickModal(playerList[id]);
        });
    }
}

function refreshLogs(logs) {
    // Remove old logs
    const playerLogLength = playerLogs.children.length;
    for (let i = 0; i < playerLogLength; i++) {
        playerLogs.children[0].remove();
    }
    const chatLogLength = chatLogs.children.length;
    for (let i = 0; i < chatLogLength; i++) {
        chatLogs.children[0].remove();
    }

    // Add logs
    for (let i = logs.length - 1; i >= 0; i--) {
        if (["join", "sync", "leave"].includes(logs[i]["type"])) {
            let content = logs[i]["player"];
            switch(logs[i]["type"]) {
                case "join":
                    content += " joined.";
                    break;
                case "sync":
                    content += " synced mods.";
                    break;
                case "leave":
                    content += " left.";
                    break;
            }
            const log = createLogDiv(content, timestamp=logs[i]["timestamp"]);
            log.style = "margin-top: 2%;";
            playerLogs.appendChild(log);
        } else if (["message"].includes(logs[i]["type"])) {
            const log = createLogDiv(logs[i]["sender"] + ((logs[i]["receiver"] != "everyone") ? " (to " + logs[i]["receiver"] + ")" : "") + ": " + logs[i]["message"], timestamp=logs[i]["timestamp"]);
            log.style = "margin-top: 2%;";
            chatLogs.appendChild(log);
        } else if (["start"].includes(logs[i]["type"])) {
            const log = createLogDiv(logs[i]["message"], timestamp=logs[i]["timestamp"], tooltipContent=null, logType="divider");
            playerLogs.appendChild(log);
            chatLogs.appendChild(log.cloneNode(true));
        }
    }
}

function refreshMapDropdown(map_input, map_label, map_button2, map_dropdown2) {
    // Remove old maps
    const levelsLength = map_dropdown2.children.length;
    for (let i = 0; i < levelsLength; i++) {
        map_dropdown2.children[0].remove();
    }

    // Add maps
    const value = server_settings["Map"];
    const levels = ((server_data.levels != null)? server_data.levels : [value]);
    const levelLength = levels.length;
    for (let i = 0; i < levelLength; i++) {
        const map_path_button = document.createElement("a");
        map_path_button.className = "dropdown-item";
        map_path_button.href = "#";
        map_path_button.innerHTML = levels[i];
        const map_path = document.createElement("li");
        map_path.appendChild(map_path_button);
        map_path_button.onclick = () => {
            map_input.value = levels[i];
            map_button2.innerHTML = levels[i];

            map_input.changed = map_input.value != value;
            map_label.style = ((map_input.changed) ? "font-style: italic;" : "");
        };
        map_dropdown2.appendChild(map_path);
    }
}

function refreshUpdateModal(modalTitle, modalContent, update = null) {
    // Remove old update files
    const updateLength = modalContent.children.length;
    for (let i = 0; i < updateLength; i++) {
        modalContent.children[0].remove();
    }

    if (update === null) {
        modalTitle.innerHTML = "Checking for Update";
        modalContent.innerHTML = "Please wait...";
    } else if (server_data["version"] == update["version"]) {
        modalTitle.innerHTML = "No Update Available";
        modalContent.innerHTML = "Server up-to-date!";
    } else {
        if (server_data["version"] == null) {
            modalTitle.innerHTML = "Unable to fetch current server version. (Latest: " + update["version"] + ")";
        } else {
            modalTitle.innerHTML = "Update Available! (" + server_data["version"] + " -> " + update["version"] + ")";
        }
        modalContent.innerHTML = "Select the update that matches your system below:";
    
        // Add files
        const files = update["files"];
        const fileLength = files.length;
        for (let i = 0; i < fileLength; i++) {
            const file = createUpdateDiv(files[i]);
            file.style = "margin-top: 3%;";
            modalContent.appendChild(file);
            const updateButton = document.getElementById(files[i]["platform"] + "." + files[i]["architecture"] + "-update");
            updateButton.addEventListener("click", () => {
                connection.send(JSON.stringify({"type": "update", "download_url": files[i]["download_url"]}));
                showToast("info", "Starting server update.");
                updateModalBS.hide();
            });
        }
    }
}

// Process server messages
connection.addEventListener("message", (event) => {
    const data = JSON.parse(event.data);
    const response = "success" in data; // Whether the server message is in response to a request sent by the client
    if (!response || Object.keys(data).length > 1) {
        // Handle responses to client requests
        if (response && "action" in data) {
            if (!data["success"]) {
                showToast("error", "An error occured in action '" + data["action"] + "', please try again later.");
            } else if (data["action"] == "restart") {
                showToast("info", "Restarted server.");
            } else if (data["action"] == "stop") {
                showToast("info", "Stopped server.");
            } else if (data["action"] == "kick") {
                showToast("info", "Kicked player.");
            } else if (data["action"] == "say") {
                showToast("info", "Sent server message.");
            } else if (data["action"] == "reloadmods") {
                showToast("info", "Reloaded mods.");
            } else if (data["action"] == "delete") {
                showToast("info", "Mod deleted.");
                connection.send(JSON.stringify({"type": "request", "request": "mod_list"}));
            } else if ((data["action"] == "enable" || data["action"] == "disable") && server_data["error"]) {
                // If the server is in an error state, server_data.mods will never change and a mod_list request will never be sent, so we send one here
                connection.send(JSON.stringify({"type": "request", "request": "mod_list"}));
            } else if (data["action"] == "update") {
                showToast("info", "Server update complete.");
            }
        } else {
            if (data["type"] && data["type"] == "settings") {
                // Update server_settings
                for (let key in data) {
                    if (key != "success" && key != "type") {
                        server_settings[key] = data[key];
                    }
                }
            } else {
                // Update server_data
                for (let key in data) {
                    if (key == "mod_list") {
                        refreshMods(data["mod_list"]);
                    } else if (key == "update") {
                        const modalTitle = document.getElementById("updateModalLabel");
                        const modalContent = document.getElementById("updateModalContent");
                        refreshUpdateModal(modalTitle, modalContent, data[key]);
                    } else if (key != "success") {
                        server_data[key] = data[key];

                        if (key == "mods") {
                            // Reload mod list on mod count change
                            connection.send(JSON.stringify({"type": "request", "request": "mod_list"}));
                        } else if (key == "levels") {
                            // Update the Map dropdown, if it exists, upon receiving the levels list
                            const input = document.getElementById("Map");
                            const label = document.getElementById("Maplabel");
                            const button2 = document.getElementById("Mapbutton2");
                            const dropdown = document.getElementById("Mapdropdown");
                            if (input !== null && label !== null && button2 !== null && dropdown !== null) {
                                refreshMapDropdown(input, label, button2, dropdown);
                            }
                        } else if (key == "players") {
                            // Reload player list on player list change
                            refreshPlayers(server_data["players"]);
                        } else if (key == "logs") {
                            // Reload player logs on join logs change
                            refreshLogs(server_data["logs"]);
                        } else if (key == "connected") {
                            // Update server connection text
                            if ("error" in server_data && server_data["error"]) {
                                continue;
                            }
                            if (server_data["connected"]) {
                                serverStatus.innerHTML = "Server Online";
                                serverStatus.style = "color: #008000; background-color: #f3f3f3; border-radius: 50px; padding: 10px;";
                            } else {
                                serverStatus.innerHTML = "Server Starting";
                                serverStatus.style = "color: #FFDE21; background-color: #f3f3f3; border-radius: 50px; padding: 10px;";
                            }
                        } else if (key == "error" && server_data["error"]) {
                            // Update server connection text
                            serverStatus.innerHTML = "Server Error";
                            serverStatus.style = "color: #FF0000; background-color: #f3f3f3; border-radius: 50px; padding: 10px;";
                        } else if (key == "version") {
                            let version;
                            if (server_data["version"] == null) {
                                version = "N/A";
                            } else {
                                version = server_data["version"];
                            }
                            serverVersion.firstChild.textContent = "BeamMP " +  version;
                        }
                    }
                }
            }
        }
    }
    console.log("Message from server ", data);
});

connection.addEventListener("open", (event) => {
    connected = true;
});

connection.addEventListener("error", (event) => {
    if (!uploadModal.ariaHidden) {
        uploadModalBS.hide();
    }
    showReloadModal();
});

connection.addEventListener("close", (event) => {
    clearInterval(pingServer); // Stop pinging the server
    if (!connected) {
        return; // Don't show disconnection modal if we were never connected
    }
    showReloadModal();
});

document.getElementById("uploadForm").addEventListener("submit", async function (event) {
    event.preventDefault();

    uploadModalButton.disabled = true;
    uploadModalButton.innerHTML = "0.00%";

    const chunkSize = 10 * 1024 * 1024; // 10MB
    const file = formFile.files[0];
    const filename = formFilename.value;

    try {
        uploadController = new AbortController();

        for (let start = 0; start < file.size; start += chunkSize) {
            const end = Math.min(start + chunkSize, file.size);
            const chunk = file.slice(start, end);

            if (end == file.size) {
                showToast("info", "File upload almost complete. Be aware this can take a few minutes.");
            }

            const formData = new FormData();
            formData.append("chunk", chunk);
            formData.append("filename", filename);

            const response = await fetch("upload", {
                method: "POST",
                headers: {
                    "Content-Range": `bytes ${start}-${end - 1}/${file.size}`,
                },
                body: formData,
            });

            const progress = start / file.size * 100;
            uploadModalButton.innerHTML = progress.toFixed(2) + "%";

            if (response.status == 201) {
                uploadModalBS.hide();
                filename = await response.text();
                showToast("info", "Uploaded mod as '" + filename + "'.");
            } else if (response.status == 206) {
                if (uploadController.signal.aborted) {
                    uploadModalBS.hide();
                    showToast("info", "Mod upload canceled.");

                    // Send abort request to server
                    const formData = new FormData();
                    formData.append("chunk", false);
                    formData.append("filename", filename);
                    await fetch("upload", {
                        method: "POST",
                        headers: {
                            "Content-Range": `bytes 0-0/${file.size}`,
                        },
                        body: formData,
                    });
                    break;
                }
                continue;
            } else if (response.status == 415) {
                uploadModalBS.hide();
                showToast("error", "Invalid file type, please upload mods as a zip archive.");
                return;
            } else if (response.status == 409) {
                uploadModalBS.hide();
                showToast("error", "A mod with that filename already exists on the server, please try again with a different filename.");
                return;
            } else if (response.status == 413) {
                uploadModalBS.hide();
                if (end == file.size) {
                    showToast("error", "Mod file too large for virus scanning, please keep unscanned mods files under 650MB.");
                } else {
                    showToast("error", "Mod file too large, please keep mod files under 1 GB.");
                }
                return;
            } else if (response.status == 422) {
                uploadModalBS.hide();
                showToast("error", "Mod file detected as malicious.");
                return;
            } else {
                uploadModalBS.hide();
                showToast("error", "Failed to upload mod, please try again later.");
                return;
            }
        }


    } catch (error) {
        uploadModalBS.hide();
        showToast("error", "Failed to upload mod, please try again later.");
    }
});

document.getElementById("cancelUpload").addEventListener("click", () => {
    if (uploadController) {
        uploadController.abort();
    }
});

document.getElementById("cancelUploadX").addEventListener("click", () => {
    if (uploadController) {
        uploadController.abort();
    }
});

document.getElementById("kickForm").addEventListener("submit", (event) => {
    event.preventDefault();
    kickModalBS.hide();
    const kickReasonValue = ((kickReason.value == "") ? "Kicked by admin" : kickReason.value);
    connection.send(JSON.stringify({"type": "command", "command": "kick", "player": kickModalLabel.innerHTML.split(" ")[1], "reason": kickReasonValue}));
});

document.getElementById("deleteModalButton").addEventListener("click", () => {
    const modName = deleteModalLabel.innerHTML.split(" ")[1];
    const deleteButton = document.getElementById(modName + "-delete-button");
    deleteButton.className = "disabled";
    deleteButton.children[0].disabled = true;
    deleteModalBS.hide();
    connection.send(JSON.stringify({"type": "delete", "delete": modName}));
});

document.getElementById("clearLogsButton").addEventListener("click", () => {
    showClearModal();
});

document.getElementById("clearModalButton").addEventListener("click", () => {
    clearModalBS.hide();
    connection.send(JSON.stringify({"type": "clear", "data": "logs"}));
});

document.getElementById("restartServerButton").addEventListener("click", () => {
    showRestartModal();
});

document.getElementById("restartModalButton").addEventListener("click", () => {
    restartModalBS.hide();
    connection.send(JSON.stringify({"type": "command", "command": "restart"}));
});

document.getElementById("reloadModsButton").addEventListener("click", () => {
    connection.send(JSON.stringify({"type": "command", "command": "reloadmods"}));
});

document.getElementById("serverMessageButton").addEventListener("click", () => {
    showMessageModal();
});

document.getElementById("messageForm").addEventListener("submit", (event) => {
    event.preventDefault();
    messageModalBS.hide();
    connection.send(JSON.stringify({"type": "command", "command": "say", "message": message.value}));
});

document.getElementById("settingButton").addEventListener("click", () => {
    showSettingModal();
});

document.getElementById("updateButton").addEventListener("click", () => {
    connection.send(JSON.stringify({"type": "request", "request": "update"}));
    showUpdateModal();
});

document.getElementById("settingModalButton").addEventListener("click", (event) => {
    event.preventDefault();
    settingModalBS.hide();
    
    const settingLength = settingForm.children.length;
    for (let i = 0; i < settingLength; i++) {
        const child = settingForm.children[i];
        if (child.tagName == "INPUT" && child.changed) {
            const value = ((child.type=="text") ? child.value : Number(child.value));
            connection.send(JSON.stringify({"type": "set", "setting": child.id, "value": value}));
        } else if (child.tagName == "DIV") {
            const checkbox = child.children.namedItem("switch");
            const level = child.children.namedItem("level");
            if (checkbox !== null) {
                if (checkbox.changed) {
                    connection.send(JSON.stringify({"type": "set", "setting": checkbox.id, "value": checkbox.checked}));
                }
            } else if (level !== null) {
                if (level.changed) {
                    connection.send(JSON.stringify({"type": "set", "setting": level.id, "value": level.value}));
                }
            }
        }
    }
    showToast("info", "Saved setting changes.");
});

document.getElementById("uploadButton").addEventListener("click", () => {
    showUploadModal();
});

homeButton.addEventListener("click", () => {
    homePage.hidden = false;
    homePage.ariaHidden = false;
    homeButton.children[0].classList.add("page-selected");
    modsPage.hidden = true;
    modsPage.ariaHidden = true;
    modsButton.children[0].classList.remove("page-selected");
    logsPage.hidden = true;
    logsPage.ariaHidden = true;
    logsButton.children[0].classList.remove("page-selected");
    configPage.hidden = true;
    configPage.ariaHidden = true;
    configButton.children[0].classList.remove("page-selected");

    refreshPlayers(server_data["players"]);
});

modsButton.addEventListener("click", () => {
    homePage.hidden = true;
    homePage.ariaHidden = true;
    homeButton.children[0].classList.remove("page-selected");
    modsPage.hidden = false;
    modsPage.ariaHidden = false;
    modsButton.children[0].classList.add("page-selected");
    logsPage.hidden = true;
    logsPage.ariaHidden = true;
    logsButton.children[0].classList.remove("page-selected");
    configPage.hidden = true;
    configPage.ariaHidden = true;
    configButton.children[0].classList.remove("page-selected");

    connection.send(JSON.stringify({"type": "request", "request": "mod_list"}));
});

logsButton.addEventListener("click", () => {
    homePage.hidden = true;
    homePage.ariaHidden = true;
    homeButton.children[0].classList.remove("page-selected");
    modsPage.hidden = true;
    modsPage.ariaHidden = true;
    modsButton.children[0].classList.remove("page-selected");
    logsPage.hidden = false;
    logsPage.ariaHidden = false;
    logsButton.children[0].classList.add("page-selected");
    configPage.hidden = true;
    configPage.ariaHidden = true;
    configButton.children[0].classList.remove("page-selected");

    refreshLogs(server_data["logs"]);
});

configButton.addEventListener("click", () => {
    homePage.hidden = true;
    homePage.ariaHidden = true;
    homeButton.children[0].classList.remove("page-selected");
    modsPage.hidden = true;
    modsPage.ariaHidden = true;
    modsButton.children[0].classList.remove("page-selected");
    logsPage.hidden = true;
    logsPage.ariaHidden = true;
    logsButton.children[0].classList.remove("page-selected");
    configPage.hidden = false;
    configPage.ariaHidden = false;
    configButton.children[0].classList.add("page-selected");
});