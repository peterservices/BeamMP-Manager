
const modsLabel = document.getElementById("modsLabel");

const mods = document.querySelector("#mods");

const modsTooltip = new bootstrap.Tooltip(modsLabel);

function formatBytes(bytes) {
    let kibibytes = bytes / (1024);
    if (kibibytes < 1) {
        return String(bytes) + " B";
    }

    let mebibytes = bytes / (1024 * 1024);
    if (mebibytes < 1) {
        return String(Math.round(kibibytes * 100) / 100) + " KiB";
    }

    let gibibytes = bytes / (1024 * 1024 * 1024);
    if (gibibytes < 1) {
        return String(Math.round(mebibytes * 100) / 100) + " MiB";
    } else {
        return String(Math.round(gibibytes * 100) / 100) + " GiB";
    }
}

function createModDiv(modName, filesize) {
    let mod = document.createElement("div");
    mod.className = "d-flex justify-content-between";

    let heading = document.createElement("h4");
    heading.className = "text-truncate"
    heading.style = "flex-grow: 1; overflow: hidden; white-space: nowrap; padding-bottom: 1%; padding-top: 1%;"
    heading.innerHTML = modName;
    heading.setAttribute("data-bs-toggle", "tooltip");
    heading.setAttribute("data-bs-title", modName);
    new bootstrap.Tooltip(heading);
    mod.appendChild(heading);

    let div = document.createElement("div");
    div.style = "flex-shrink: 0;"
    mod.appendChild(div);

    let aDownload = document.createElement("a");
    aDownload.id = modName + "-download";
    aDownload.href = "mods/" + modName;
    aDownload.download = modName;
    aDownload.style = "text-decoration: none;"
    aDownload.setAttribute("data-bs-toggle", "tooltip");
    let size = formatBytes(filesize);
    aDownload.setAttribute("data-bs-title", "Download (" + size + ")");
    new bootstrap.Tooltip(aDownload);
    div.appendChild(aDownload);

    let download = document.createElement("button");
    download.type = "button";
    download.className = "btn download-button"
    aDownload.appendChild(download);

    let image = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    image.setAttribute("width", "16");
    image.setAttribute("height", "16");
    image.setAttribute("fill", "currentColor");
    image.classList.add("bi", "bi-download");
    image.setAttribute("viewBox", "0 0 16 16");
    download.appendChild(image);
    
    let path1 = document.createElementNS(image.namespaceURI, "path");
    path1.setAttributeNS(null, "d", "M.5 9.9a.5.5 0 0 1 .5.5v2.5a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-2.5a.5.5 0 0 1 1 0v2.5a2 2 0 0 1-2 2H2a2 2 0 0 1-2-2v-2.5a.5.5 0 0 1 .5-.5");
    image.appendChild(path1);

    let path2 = document.createElementNS(image.namespaceURI, "path");
    path2.setAttributeNS(null, "d", "M7.646 11.854a.5.5 0 0 0 .708 0l3-3a.5.5 0 0 0-.708-.708L8.5 10.293V1.5a.5.5 0 0 0-1 0v8.793L5.354 8.146a.5.5 0 1 0-.708.708z");
    image.appendChild(path2);

    return mod;
}

function refreshMods(modsList) {
    // Remove old mods
    let modsLength = mods.children.length;
    for (let i = 0; i < modsLength; i++) {
        mods.children[0].remove();
    }

    // Add mods
    let total = 0;
    let bytes = 0;
    for (let key in modsList) {
        total++;
        bytes += modsList[key]["filesize"];
        let mod = createModDiv(key, modsList[key]["filesize"]);
        mod.style = "margin-top: 2%;";
        mods.appendChild(mod);
    }
    modsTooltip.setContent({".tooltip-inner": String(total) + " (" + formatBytes(bytes) + ")"});
}

fetch("mods_list").then((resp) => {
    resp.json().then((value) => {
        console.log(value);
        refreshMods(value);
    })
})