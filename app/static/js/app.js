import { hideModal, showModal } from "./utils.js?v=3";
import { createApi } from "./api.js?v=1";

const homeUrl = document.querySelector(".navbar-brand").href;
const pageMessage = document.getElementById("pageMessage");
const postDetail = document.getElementById("postDetail");
const accountPage = document.getElementById("accountPage");
const profileForm = document.getElementById("profileForm");
const imageForm = document.getElementById("profileImageForm");
const profileInput = document.getElementById("profileImage");
const profilePreview = document.getElementById("profileImagePreview");
const resetPicture = document.getElementById("resetProfileImage");
let currentUser = null;
let pendingNewPost = false;
let previewUrl = null;
let profileBusy = false;

function message(text, type = "success") {
    pageMessage.textContent = text;
    pageMessage.className = `alert alert-${type}`;
    pageMessage.hidden = false;
}

function updateUser(user) {
    const previousUser = currentUser;
    currentUser = user;
    document.querySelectorAll("[data-auth-only]").forEach(element => {
        element.hidden = !user;
    });
    document.querySelectorAll("[data-guest-only]").forEach(element => {
        element.hidden = Boolean(user);
    });
    document.getElementById("currentUsername").textContent = user?.username || "";
    if (user) {
        document.querySelectorAll("[data-profile-user-id]").forEach(image => {
            if (Number(image.dataset.profileUserId) === user.id) image.src = user.image_path;
        });
    }
    document.querySelectorAll("[data-my-posts]").forEach(link => {
        if (user) link.href = new URL(`users/${user.id}/posts`, homeUrl).href;
        else link.removeAttribute("href");
    });
    if (postDetail) {
        document.getElementById("postActions").hidden =
            !user || user.id !== Number(postDetail.dataset.authorId);
    }
    renderAccount(user, previousUser);
}

const api = createApi(homeUrl, () => updateUser(null));

const sessionReady = api("users/me").then(updateUser).catch(error => {
    updateUser(null);
    if (error.status !== 401) message(error.message, "danger");
});

function bindForm(id, action) {
    const form = document.getElementById(id);
    if (!form) return;
    form.addEventListener("submit", async event => {
        event.preventDefault();
        const button = form.querySelector('button[type="submit"]');
        if (button.disabled || !form.reportValidity()) return;
        const errorBox = form.querySelector("[data-form-error]");
        const label = button.textContent;
        errorBox.hidden = true;
        button.disabled = true;
        button.textContent = "Please wait...";
        try {
            await action(Object.fromEntries(new FormData(form)), form);
        } catch (error) {
            errorBox.textContent = error.message;
            errorBox.hidden = false;
        } finally {
            button.disabled = false;
            button.textContent = label;
        }
    });
}

async function success(sourceModal, text, destination) {
    document.getElementById("successMessage").textContent = text;
    if (destination) {
        document.getElementById("successModal").addEventListener("hidden.bs.modal", () => {
            window.location.assign(destination);
        }, { once: true });
    }
    await hideModal(sourceModal);
    showModal("successModal");
}

document.querySelectorAll("[data-new-post]").forEach(button => {
    button.addEventListener("click", async () => {
        await sessionReady;
        if (currentUser) {
            showModal("createPostModal");
        } else {
            pendingNewPost = true;
            const notice = document.getElementById("loginNotice");
            notice.textContent = "Log in to write a post.";
            notice.hidden = false;
            showModal("loginModal");
        }
    });
});

bindForm("registerForm", async (data, form) => {
    if (data.password !== data.confirm_password) throw new Error("Passwords do not match.");
    const user = await api("users/register", {
        method: "POST",
        body: { username: data.username.trim(), email: data.email.trim(), password: data.password },
    });
    form.reset();
    document.getElementById("loginUsername").value = user.username;
    document.getElementById("loginPassword").value = "";
    const notice = document.getElementById("loginNotice");
    notice.textContent = "Account created. Log in to continue.";
    notice.hidden = false;
    await hideModal("registerModal");
    showModal("loginModal");
});

bindForm("loginForm", async (data, form) => {
    await sessionReady;
    const user = await api("users/login", {
        method: "POST", body: { username: data.username.trim(), password: data.password },
    });
    updateUser(user);
    form.reset();
    document.getElementById("loginNotice").hidden = true;
    await hideModal("loginModal");
    message(`Welcome, ${user.username}!`);
    if (pendingNewPost) {
        pendingNewPost = false;
        showModal("createPostModal");
    }
});

function renderAccount(user, previousUser) {
    if (!accountPage) return;
    document.getElementById("accountLoading").hidden = true;
    document.getElementById("accountContent").hidden = !user;
    document.getElementById("accountSignIn").hidden = Boolean(user);
    const changedAccount = user?.id !== previousUser?.id;
    if (!user || changedAccount) {
        profileForm.reset();
        imageForm.reset();
        profileInput.setCustomValidity("");
        accountPage.querySelectorAll("[data-form-error]").forEach(error => { error.hidden = true; });
        clearProfilePreview();
    }
    document.getElementById("profileUsername").textContent = user?.username || "";
    document.getElementById("profileEmail").textContent = user?.email || "";
    if (user) {
        // Saving a picture must not discard unsaved edits to the profile fields.
        if (changedAccount || user.username !== previousUser?.username) {
            document.getElementById("accountUsername").value = user.username;
        }
        if (changedAccount || user.email !== previousUser?.email) {
            document.getElementById("accountEmail").value = user.email;
        }
        if (!profileInput.files.length) clearProfilePreview();
    }
    resetPicture.disabled = profileBusy || !user?.image_file;
}

function clearProfilePreview() {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = null;
    profilePreview.src = currentUser?.image_path || new URL("static/profile_pics/default.jpg", homeUrl).href;
}

function setProfileBusy(busy) {
    profileBusy = busy;
    document.getElementById("accountContent").querySelectorAll("button, input").forEach(control => {
        control.disabled = busy;
    });
    resetPicture.disabled = busy || !currentUser?.image_file;
}

bindForm("profileForm", async data => {
    if (!currentUser) throw new Error("Please log in to continue.");
    const body = { username: data.username.trim(), email: data.email.trim() };
    if (!body.username || !body.email) throw new Error("Please enter a username and email.");
    setProfileBusy(true);
    try {
        const user = await api(`users/${currentUser.id}/update`, { method: "PATCH", body });
        updateUser(user);
        document.getElementById("accountUsername").value = user.username;
        document.getElementById("accountEmail").value = user.email;
        message("Profile updated successfully.");
    } finally {
        setProfileBusy(false);
    }
});

profileInput?.addEventListener("change", () => {
    clearProfilePreview();
    profileInput.setCustomValidity("");
    imageForm.querySelector("[data-form-error]").hidden = true;
    const file = profileInput.files[0];
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) {
        profileInput.setCustomValidity("Profile pictures must be 5 MB or smaller.");
    } else if (file.type && !["image/jpeg", "image/png", "image/webp"].includes(file.type)) {
        profileInput.setCustomValidity("Choose a JPEG, PNG, or WebP image.");
    }
    if (!profileInput.reportValidity()) return;
    previewUrl = URL.createObjectURL(file);
    profilePreview.src = previewUrl;
});

bindForm("profileImageForm", async () => {
    if (!currentUser) throw new Error("Please log in to continue.");
    const body = new FormData(imageForm);
    setProfileBusy(true);
    try {
        updateUser(await api("users/me/image", { method: "PUT", body }));
        imageForm.reset();
        clearProfilePreview();
    } finally {
        setProfileBusy(false);
    }
    message("Profile picture updated.");
});

resetPicture?.addEventListener("click", async () => {
    if (profileBusy) return;
    const errorBox = imageForm.querySelector("[data-form-error]");
    errorBox.hidden = true;
    setProfileBusy(true);
    try {
        updateUser(await api("users/me/image", { method: "DELETE" }));
        imageForm.reset();
        profileInput.setCustomValidity("");
        clearProfilePreview();
        message("Default profile picture restored.");
    } catch (error) {
        errorBox.textContent = error.message;
        errorBox.hidden = false;
    } finally {
        setProfileBusy(false);
    }
});

document.getElementById("logoutButton").addEventListener("click", async event => {
    const button = event.currentTarget;
    if (button.disabled) return;
    button.disabled = true;
    try {
        await api("users/logout", { method: "POST" });
        updateUser(null);
        pendingNewPost = false;
        document.getElementById("createPostForm").reset();
        message("You have been logged out.");
    } catch (error) {
        message(error.message, "danger");
    } finally {
        button.disabled = false;
    }
});

function postFields(data) {
    const title = data.title.trim();
    const content = data.content.trim();
    if (!title || !content) throw new Error("Please enter a title and content.");
    return { title, content };
}

bindForm("createPostForm", async (data, form) => {
    const post = await api("posts/", { method: "POST", body: postFields(data) });
    form.reset();
    await success("createPostModal", `Post "${post.title}" created successfully!`,
        new URL(`posts/${post.id}`, homeUrl).href);
});

if (postDetail) {
    const postPath = `posts/${postDetail.dataset.postId}`;
    document.getElementById("editPostModal").addEventListener("show.bs.modal", () => {
        document.getElementById("editTitle").value = postDetail.querySelector(".article-title").textContent;
        document.getElementById("editContent").value = postDetail.querySelector(".article-content").textContent;
        document.querySelector("#editPostForm [data-form-error]").hidden = true;
    });
    bindForm("editPostForm", async data => {
        const post = await api(postPath, { method: "PATCH", body: postFields(data) });
        postDetail.querySelector(".article-title").textContent = post.title;
        postDetail.querySelector(".article-content").textContent = post.content;
        document.title = `FastAPI Blog - ${post.title.slice(0, 50)}`;
        await success("editPostModal", "Post updated successfully!");
    });
    bindForm("deletePostForm", async () => {
        await api(postPath, { method: "DELETE" });
        window.location.assign(homeUrl);
    });
}

// Refresh ownership controls if another tab logged in or out.
window.addEventListener("pageshow", event => {
    if (event.persisted) api("users/me").then(updateUser).catch(() => updateUser(null));
});
