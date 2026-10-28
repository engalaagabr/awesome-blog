import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { createApi } from "../app/static/js/api.js";

const originalFetch = globalThis.fetch;
const originalNavigator = Object.getOwnPropertyDescriptor(globalThis, "navigator");
afterEach(() => {
    globalThis.fetch = originalFetch;
    if (originalNavigator) Object.defineProperty(globalThis, "navigator", originalNavigator);
    else delete globalThis.navigator;
});

const response = (status, data = { detail: "Please log in to continue" }) =>
    new Response(status === 204 ? null : JSON.stringify(data), { status });

test("expired access is refreshed and the original JSON request is retried once", async () => {
    const calls = [];
    const responses = [response(401), response(401), response(200), response(201, { id: 1 })];
    globalThis.fetch = async (url, options) => {
        calls.push([url.pathname, options]);
        return responses.shift();
    };
    let loggedOut = false;
    const api = createApi("https://test/", () => { loggedOut = true; });
    assert.deepEqual(await api("posts/", { method: "POST", body: { title: "Draft", content: "Body" } }), { id: 1 });
    assert.deepEqual(calls.map(([path]) => path), [
        "/api/posts/", "/api/users/me", "/api/users/refresh", "/api/posts/",
    ]);
    assert.deepEqual(calls[0][1], calls[3][1]);
    assert.equal(calls[2][1].method, "POST");
    assert.equal(calls[2][1].credentials, "same-origin");
    assert.equal(loggedOut, false);
});

test("concurrent unauthorized requests share a single refresh", async () => {
    let refreshed = false;
    let refreshes = 0;
    globalThis.fetch = async url => {
        if (url.pathname === "/api/users/refresh") {
            refreshes += 1;
            await new Promise(resolve => setImmediate(resolve));
            refreshed = true;
            return response(200);
        }
        return refreshed ? response(200, { id: 1 }) : response(401);
    };
    const api = createApi("https://test/", () => assert.fail("should stay logged in"));
    const results = await Promise.all([api("users/me"), api("posts/", { method: "POST", body: {} })]);
    assert.deepEqual(results, [{ id: 1 }, { id: 1 }]);
    assert.equal(refreshes, 1);
});

test("a late 401 uses the newly refreshed session without rotating again", async () => {
    let refreshed = false;
    let refreshes = 0;
    let releaseLate;
    let lateStarted;
    const started = new Promise(resolve => { lateStarted = resolve; });
    const lateResponse = new Promise(resolve => { releaseLate = resolve; });
    globalThis.fetch = async url => {
        if (url.pathname === "/api/late" && !refreshed) {
            lateStarted();
            return lateResponse;
        }
        if (url.pathname === "/api/users/refresh") {
            refreshes += 1;
            refreshed = true;
            return response(200);
        }
        return response(refreshed ? 200 : 401, { id: 1 });
    };
    const api = createApi("https://test/", () => assert.fail("should stay logged in"));
    const late = api("late");
    await started;
    await api("users/me");
    releaseLate(response(401));
    assert.deepEqual(await late, { id: 1 });
    assert.equal(refreshes, 1);
});

test("two tabs serialize rotation using Web Locks and recheck shared cookies", async () => {
    let queue = Promise.resolve();
    Object.defineProperty(globalThis, "navigator", { configurable: true, value: {
        locks: { request: (name, action) => {
            assert.equal(name, "blog-session-refresh");
            const result = queue.then(action);
            queue = result.catch(() => {});
            return result;
        } },
    } });
    let refreshed = false;
    let refreshes = 0;
    globalThis.fetch = async url => {
        if (url.pathname === "/api/users/refresh") {
            refreshes += 1;
            await new Promise(resolve => setImmediate(resolve));
            refreshed = true;
        }
        return response(refreshed ? 200 : 401, { id: 1 });
    };
    const first = createApi("https://test/", () => assert.fail("first tab logged out"));
    const second = createApi("https://test/", () => assert.fail("second tab logged out"));
    await Promise.all([first("users/me"), second("users/me")]);
    assert.equal(refreshes, 1);
});

test("expired refresh logs out and never retries the write", async () => {
    const paths = [];
    globalThis.fetch = async url => {
        paths.push(url.pathname);
        return response(401);
    };
    let logouts = 0;
    const api = createApi("https://test/", () => { logouts += 1; });
    await assert.rejects(api("posts/", { method: "POST", body: {} }), { status: 401 });
    assert.deepEqual(paths, ["/api/posts/", "/api/users/me", "/api/users/refresh"]);
    assert.equal(logouts, 1);
});

test("a retried 401 does not start an infinite refresh loop", async () => {
    let refreshes = 0;
    let logouts = 0;
    globalThis.fetch = async url => {
        if (url.pathname === "/api/users/refresh") {
            refreshes += 1;
            return response(200);
        }
        return response(401);
    };
    const api = createApi("https://test/", () => { logouts += 1; });
    await assert.rejects(api("users/me"), { status: 401 });
    assert.equal(refreshes, 1);
    assert.equal(logouts, 1);
});

test("login failures and forbidden requests do not trigger refresh", async () => {
    const paths = [];
    globalThis.fetch = async url => {
        paths.push(url.pathname);
        return response(url.pathname === "/api/users/login" ? 401 : 403);
    };
    const api = createApi("https://test/", () => assert.fail("should not log out"));
    await assert.rejects(api("users/login", { method: "POST", body: {} }), { status: 401 });
    await assert.rejects(api("posts/1", { method: "DELETE" }), { status: 403 });
    assert.deepEqual(paths, ["/api/users/login", "/api/posts/1"]);
});

test("transient refresh failures preserve login state and allow a later attempt", async () => {
    let refreshes = 0;
    let refreshed = false;
    globalThis.fetch = async url => {
        if (url.pathname === "/api/users/refresh") {
            refreshes += 1;
            if (refreshes === 1) throw new Error("offline");
            refreshed = true;
        }
        return response(refreshed ? 200 : 401, { id: 1 });
    };
    const api = createApi("https://test/", () => assert.fail("should not log out"));
    await assert.rejects(api("users/me"), /Unable to reach the server/);
    assert.deepEqual(await api("users/me"), { id: 1 });
    assert.equal(refreshes, 2);
});

test("multipart bodies survive a retry and 204 responses remain empty", async () => {
    const body = new FormData();
    body.append("image", new Blob(["image bytes"], { type: "image/png" }), "avatar.png");
    let writes = 0;
    globalThis.fetch = async (url, options) => {
        if (url.pathname === "/api/users/me/image") {
            writes += 1;
            assert.equal(options.body, body);
            assert.deepEqual(options.headers, {});
            return response(writes === 1 ? 401 : 204);
        }
        return response(url.pathname === "/api/users/refresh" ? 200 : 401);
    };
    const api = createApi("https://test/", () => assert.fail("should stay logged in"));
    assert.equal(await api("users/me/image", { method: "PUT", body }), null);
    assert.equal(writes, 2);
});
