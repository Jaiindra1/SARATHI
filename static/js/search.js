// Find the existing search form.
const searchForm = document.getElementById("search-form");

// Find the loading overlay.
const searchLoader = document.getElementById("search-loader");

// Find the loading message.
const loaderMessage = document.getElementById("loader-message");

// Find the product results container.
const resultsContainer = document.getElementById("results-container");


// Messages that rotate while products are being fetched.
const loadingMessages = [
    "I'm getting product details...",
    "Searching Flipkart and Amazon...",
    "Collecting product prices...",
    "Checking available products...",
    "Almost there! Preparing your results..."
];


// Change the loading message every three seconds.
let messageInterval = null;


// Each HTTP request is short; Selenium continues independently.
const REQUEST_TIMEOUT = 15000;
let searchInProgress = false;
let pageLeaving = false;
let pendingSubmission = null;
// Persist only an unacknowledged submission, so reload can recover a lost response.
try {
    const saved = JSON.parse(sessionStorage.getItem("sarathi-pending-search"));
    if (saved && /^[0-9a-f]{32}$/.test(saved.request_id) &&
        typeof saved.query === "string" && saved.query.trim() && saved.query.length <= 200) {
        pendingSubmission = saved;
    }
} catch { /* Storage may be unavailable; in-page retries still work. */ }

function savePendingSubmission(value) {
    pendingSubmission = value;
    try {
        if (value) sessionStorage.setItem("sarathi-pending-search", JSON.stringify(value));
        else sessionStorage.removeItem("sarathi-pending-search");
    } catch { /* Storage is optional. */ }
}

function newRequestId() {
    const bytes = new Uint8Array(16);
    window.crypto.getRandomValues(bytes);
    return Array.from(bytes, byte => byte.toString(16).padStart(2, "0")).join("");
}


// Show the loading animation.
function showLoader() {

    searchLoader.classList.add("active");
    searchLoader.setAttribute("aria-hidden", "false");

    if (messageInterval !== null) clearInterval(messageInterval);
    searchForm.querySelector('button[type="submit"]').disabled = true;
    resultsContainer.setAttribute("aria-busy", "true");
    let messageIndex = 0;

    loaderMessage.textContent = loadingMessages[messageIndex];

    messageInterval = setInterval(() => {

        messageIndex = (messageIndex + 1) % loadingMessages.length;

        loaderMessage.textContent = loadingMessages[messageIndex];

    }, 3000);
}


// Hide the loading animation.
function hideLoader() {

    searchForm.querySelector('button[type="submit"]').disabled = false;
    resultsContainer.setAttribute("aria-busy", "false");
    searchLoader.classList.remove("active");
    searchLoader.setAttribute("aria-hidden", "true");

    if (messageInterval !== null) {
        clearInterval(messageInterval);
        messageInterval = null;
    }
}


// Safely create a text element.
function createTextElement(tag, text, className = "") {

    const element = document.createElement(tag);

    element.textContent = text ?? "";

    if (className) {
        element.className = className;
    }

    return element;
}


// Accept only valid HTTP or HTTPS URLs.
function isSafeUrl(value) {

    if (typeof value !== "string" || !value.trim()) {
        return false;
    }

    try {
        const url = new URL(value);

        return url.protocol === "http:" || url.protocol === "https:";

    } catch {
        return false;
    }
}


// Display products returned by Flask.
function displayProducts(products) {

    resultsContainer.replaceChildren();

    if (!products || products.length === 0) {

        resultsContainer.append(
            createTextElement("p", "No matching products found.")
        );

        return;
    }

    const grid = document.createElement("div");
    grid.className = "products-grid";

    products.forEach(product => {

        const card = document.createElement("div");
        card.className = "product-card";

        card.append(
            createTextElement("p", product.retailer, "product-retailer")
        );

        if (isSafeUrl(product.image_url)) {

            const image = document.createElement("img");

            image.src = product.image_url;
            image.alt = product.name || "Product image";
            image.loading = "lazy";

            const wrapper = document.createElement("div");
            wrapper.className = "product-image-wrapper";
            wrapper.append(image);
            card.append(wrapper);
        }

        card.append(
            createTextElement("h3", product.name, "product-title")
        );

        if (Array.isArray(product.highlights) && product.highlights.length) {
            const highlights = document.createElement("div");
            highlights.className = "product-highlights";
            product.highlights.slice(0, 5).forEach(highlight => {
                if (typeof highlight === "string" && highlight.trim()) {
                    highlights.append(createTextElement("span", highlight, "highlight-chip"));
                }
            });
            if (highlights.childElementCount) card.append(highlights);
        }

        if (product.price !== null && product.price !== undefined) {
            card.append(
                createTextElement(
                    "p",
                    `₹${product.price}`,
                    "product-price"
                )
            );
        }

        if (product.original_price !== null &&
            product.original_price !== undefined) {

            card.append(
                createTextElement(
                    "p",
                    `Original price: ₹${product.original_price}`,
                    "product-original-price"
                )
            );
        }

        if (product.rating !== null && product.rating !== undefined) {
            card.append(
                createTextElement("p", `Rating: ${product.rating}`, "product-rating")
            );
        }

        if (product.availability) {
            card.append(
                createTextElement("p", product.availability, "product-availability")
            );
        }

        if (isSafeUrl(product.url)) {

            const link = document.createElement("a");

            link.className = "product-button";
            link.href = product.url;
            link.target = "_blank";
            link.rel = "noopener noreferrer";
            link.textContent = "View Product";

            card.append(link);
        }

        grid.append(card);
    });

    resultsContainer.append(grid);
}


// Fetch with a per-request deadline, including JSON body reading.
async function requestJson(url, options = {}) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT);
    try {
        const response = await fetch(url, { ...options, cache: "no-store", signal: controller.signal });
        let data;
        try {
            data = await response.json();
        } catch (error) {
            if (error.name === "AbortError" || error instanceof TypeError) throw error;
            throw new Error("The service returned an unexpected response. It may be restarting. Please try again shortly.");
        }
        if (!response.ok) {
            const error = new Error(data.message || "The service is unavailable. Please try again shortly.");
            error.status = response.status;
            throw error;
        }
        return data;
    } finally {
        clearTimeout(timeoutId);
    }
}

function retailerSummary(retailers) {
    return Object.entries(retailers || {}).map(([name, outcome]) => {
        const detail = outcome.status === "failed" ? ` (${outcome.stage || "search failure"})` : "";
        return `${name}: ${outcome.status}${detail}`;
    }).join(". ");
}

function showSearchError(error) {
    const message = error.name === "AbortError"
        ? "The service is taking too long to respond. Your search may still be running. Reload this page to reconnect."
        : error instanceof TypeError
            ? "Connection lost. Your search may still be running. Reload this page to reconnect."
            : error.message;
    resultsContainer.replaceChildren(createTextElement("p", message));
}

async function followJob(jobId) {
    if (messageInterval !== null) {
        clearInterval(messageInterval);
        messageInterval = null;
    }
    const base = `/api/search/${encodeURIComponent(jobId)}`;
    // Keep the job in the URL so reloads can reconnect without submitting again.
    const url = new URL(window.location.href);
    url.searchParams.set("job", jobId);
    history.replaceState(null, "", url);
    resultsContainer.dataset.jobId = jobId;
    let failures = 0;
    while (!pageLeaving) {
        let job;
        try {
            job = await requestJson(`${base}/status`);
            failures = 0;
        } catch (error) {
            // Retry transient connection failures, but stop for missing/expired jobs.
            if ((error.name === "AbortError" || error instanceof TypeError) && ++failures < 3) {
                loaderMessage.textContent = "Reconnecting to your search...";
                await new Promise(resolve => setTimeout(resolve, 2000));
                continue;
            }
            throw error;
        }
        if (job.status === "completed" || job.status === "failed") {
            const result = await requestJson(`${base}/results`);
            if (result.status === "failed") {
                resultsContainer.replaceChildren(createTextElement("p", result.message));
            } else {
                displayProducts(result.products);
            }
            if (result.persistence?.warning) {
                resultsContainer.prepend(createTextElement("p", result.persistence.warning));
            }
            resultsContainer.append(createTextElement("p", retailerSummary(result.retailers)));
            return;
        }
        if (!["queued", "running"].includes(job.status)) {
            throw new Error("The service returned an unknown search status. Please reload to reconnect.");
        }
        loaderMessage.textContent = retailerSummary(job.retailers) || job.message;
        await new Promise(resolve => setTimeout(resolve, 2000));
    }
}

async function runSearch(query, existingJobId = "") {
    if (searchInProgress) return;
    searchInProgress = true;
    showLoader();
    try {
        let jobId = existingJobId;
        if (!jobId) {
            if (!pendingSubmission || pendingSubmission.query !== query) {
                savePendingSubmission({ query, request_id: newRequestId() });
            }
            // Do not reconnect to an older job if this submission loses its response.
            const url = new URL(window.location.href);
            url.searchParams.delete("job");
            history.replaceState(null, "", url);
            resultsContainer.dataset.jobId = "";
            let data;
            for (let attempt = 0; attempt < 3; attempt++) {
                try {
                    data = await requestJson("/api/search", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(pendingSubmission),
                    });
                    break;
                } catch (error) {
                    if (error.status >= 400 && error.status < 500) savePendingSubmission(null);
                    if ((error.name === "AbortError" || error instanceof TypeError) && attempt < 2 && !pageLeaving) {
                        loaderMessage.textContent = "Reconnecting to your search submission...";
                        await new Promise(resolve => setTimeout(resolve, 2000));
                        continue;
                    }
                    throw error;
                }
            }
            jobId = data.job_id;
            if (!jobId) throw new Error("The service did not return a search ID. Reload to retry this submission.");
            // Save the acknowledged job before clearing the pending request.
            url.searchParams.set("job", jobId);
            history.replaceState(null, "", url);
            savePendingSubmission(null);
        }
        await followJob(jobId);
    } catch (error) {
        if (!pageLeaving) showSearchError(error);
    } finally {
        searchInProgress = false;
        hideLoader();
    }
}

searchForm.addEventListener("submit", event => {
    event.preventDefault();
    const query = new FormData(searchForm).get("query")?.trim();
    if (!query) {
        resultsContainer.replaceChildren(createTextElement("p", "Please enter a product name."));
        return;
    }
    runSearch(query);
});

function initializeSearch() {
    if (searchInProgress) return;
    const jobId = resultsContainer.dataset.jobId;
    if (pendingSubmission) runSearch(pendingSubmission.query);
    else if (jobId) runSearch(null, jobId);
    else hideLoader();
}

if (document.readyState === "complete") initializeSearch();
else window.addEventListener("load", initializeSearch, { once: true });
window.addEventListener("pagehide", () => { pageLeaving = true; });
window.addEventListener("pageshow", event => {
    if (event.persisted) window.location.reload();
});
