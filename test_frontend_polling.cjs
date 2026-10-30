// Controlled DOM, real localhost Flask API. No browser or retailer traffic.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const { webcrypto } = require("node:crypto");

const base = process.env.SARATHI_TEST_BASE_URL;
assert(base, "Run through test_frontend_integration.py");
const source = fs.readFileSync("static/js/search.js", "utf8");

function element() {
    return {
        children: [], dataset: {}, textContent: "",
        classList: { add() {}, remove() {} },
        setAttribute() {}, addEventListener() {},
        querySelector() { return {}; },
        append(...items) { this.children.push(...items); },
        prepend(...items) { this.children.unshift(...items); },
        replaceChildren(...items) { this.children = items; },
        get childElementCount() { return this.children.length; },
    };
}
function textOf(node) {
    return [node.textContent, ...node.children.map(textOf)].join(" ");
}

async function search(query, loseResponse = false) {
    const nodes = Object.fromEntries(
        ["search-form", "search-loader", "loader-message", "results-container"].map(id => [id, element()])
    );
    const storage = new Map();
    const requests = [];
    let href = base + "/";
    let first = true;
    const context = vm.createContext({
        document: {
            getElementById: id => nodes[id],
            createElement: () => element(),
            readyState: "loading",
        },
        window: {
            location: { get href() { return href; } },
            crypto: webcrypto, addEventListener() {},
        },
        history: { replaceState(a, b, value) { href = String(value); } },
        sessionStorage: {
            getItem: key => storage.get(key) || null,
            setItem: (key, value) => storage.set(key, value),
            removeItem: key => storage.delete(key),
        },
        URL, Uint8Array, AbortController, Error, TypeError, console,
        setInterval: () => 1, clearInterval() {}, clearTimeout,
        setTimeout: (fn, ms) => setTimeout(fn, ms === 2000 ? 1 : ms),
        fetch: async (path, options) => {
            const response = await fetch(new URL(path, base), options);
            requests.push({ path, body: options.body, code: response.status });
            if (path === "/api/search" && first) {
                first = false;
                if (loseResponse) {
                    await response.arrayBuffer();
                    throw new TypeError("Simulated lost submission response");
                }
            }
            return response;
        },
    });
    vm.runInContext(source, context);
    await vm.runInContext("runSearch(" + JSON.stringify(query) + ")", context);
    return { content: textOf(nodes["results-container"]), requests, href, storage };
}

(async () => {
    let result = await search("phone", true);
    const submissions = result.requests.filter(request => request.path === "/api/search");
    assert.equal(submissions.length, 2);
    assert.equal(submissions[0].body, submissions[1].body);
    assert(submissions.every(request => request.code === 202));
    assert(result.requests.some(request => request.path.endsWith("/status")));
    assert(result.requests.some(request => request.path.endsWith("/results")));
    assert.match(result.content, /Example phone/);
    assert(result.content.includes("\u20b9100"));
    assert(result.content.includes("Original price: \u20b9150"));
    assert.match(result.content, /Amazon: completed/);
    assert.match(result.content, /Flipkart: completed/);
    assert.equal(result.storage.size, 0);
    assert.match(result.href, /job=/);
    console.log("PASS lost-response retry -> real API job -> SQLite -> polling -> existing product cards");

    result = await search("storage-failure");
    assert.match(result.content, /Example phone/);
    assert.match(result.content, /SQLite/);
    assert.match(result.content, /did not fully complete/);
    console.log("PASS SQLite failure warning remains visible alongside rendered cards");

    result = await search("both-fail");
    assert.match(result.content, /Retailer searches are unavailable/);
    assert.match(result.content, /blocked_page/);
    console.log("PASS failed job and retailer outcome display");
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
