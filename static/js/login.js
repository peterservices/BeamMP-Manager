const unauthorizedToast = document.getElementById("unauthorizedToast");
const errorToast = document.getElementById("errorToast");

const data = document.getElementById("error-data").textContent;

if (data == "error") {
    const toastBootstrap = bootstrap.Toast.getOrCreateInstance(errorToast);
    toastBootstrap.show();
} else if (data == "unauthorized") {
    const toastBootstrap = bootstrap.Toast.getOrCreateInstance(unauthorizedToast);
    toastBootstrap.show();
}