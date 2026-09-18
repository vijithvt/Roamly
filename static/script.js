let currentThreadId = localStorage.getItem("travel_thread_id") || null;
let latestAnswerMarkdown = "";
let latestUserQuery = "";
let latestStartDate = "";
let latestEndDate = "";
let activeEventSource = null;

function setPrompt(text) {
    document.getElementById("userInput").value = text;
}

function setLoading(isLoading) {
    const sendBtn = document.getElementById("sendBtn");
    const btnText = document.getElementById("btnText");
    const btnLoader = document.getElementById("btnLoader");

    sendBtn.disabled = isLoading;

    if (isLoading) {
        btnText.classList.add("hidden");
        btnLoader.classList.remove("hidden");
    } else {
        btnText.classList.remove("hidden");
        btnLoader.classList.add("hidden");
    }
}

function showError(message) {
    const errorBox = document.getElementById("errorBox");

    errorBox.textContent = message;
    errorBox.classList.remove("hidden");
}

function hideError() {
    const errorBox = document.getElementById("errorBox");

    errorBox.classList.add("hidden");
    errorBox.textContent = "";
}

function formatDateLabel(dateStr) {
    if (!dateStr) {
        return "";
    }

    const d = new Date(`${dateStr}T00:00:00`);

    if (isNaN(d.getTime())) {
        return dateStr;
    }

    return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

const SECTION_ICONS = [
    { match: /flight/i, icon: "✈️" },
    { match: /bus/i, icon: "🚌" },
    { match: /hotel/i, icon: "🏨" },
    { match: /weather/i, icon: "🌦️" },
    { match: /itinerary|day[- ]by[- ]day/i, icon: "🗺️" },
    { match: /budget/i, icon: "💰" },
    { match: /package/i, icon: "📦" },
    { match: /book/i, icon: "🎫" },
    { match: /recommend/i, icon: "✅" },
    { match: /summary/i, icon: "📋" },
];

function addSectionIcons(container) {
    container.querySelectorAll("h1, h2").forEach((heading) => {
        const found = SECTION_ICONS.find((entry) => entry.match.test(heading.textContent));

        if (found && !heading.textContent.trim().startsWith(found.icon)) {
            heading.textContent = `${found.icon} ${heading.textContent.trim()}`;
        }
    });
}

async function fetchWikiImage(title) {
    const response = await fetch(
        `https://en.wikipedia.org/api/rest_v1/page/summary/${encodeURIComponent(title)}`
    );

    if (!response.ok) {
        return null;
    }

    const data = await response.json();
    const source = (data.originalimage && data.originalimage.source) || (data.thumbnail && data.thumbnail.source);

    if (!source) {
        return null;
    }

    // Country/region pages often lead with a flag, coat of arms, or a
    // locator map instead of a scenic photo - skip those.
    if (/flag_of|coat_of_arms|_locator_|orthographic|\.svg(\?|$)/i.test(source)) {
        return null;
    }

    return source;
}

async function loadDestinationImage(destination) {
    const img = document.getElementById("destinationImage");
    const caption = document.getElementById("destinationCaption");

    img.classList.add("hidden");
    caption.classList.add("hidden");
    img.removeAttribute("src");

    if (!destination) {
        return;
    }

    // Try a tourism-focused page first (better odds of a scenic photo for
    // country-level destinations), then fall back to the plain place name.
    const candidates = [`Tourism in ${destination}`, destination];

    try {
        let source = null;

        for (const title of candidates) {
            source = await fetchWikiImage(title).catch(() => null);
            if (source) {
                break;
            }
        }

        if (!source) {
            return;
        }

        await new Promise((resolve) => {
            img.onload = resolve;
            img.onerror = resolve;
            img.src = source;
        });

        if (!img.naturalWidth) {
            // Failed to load (e.g. blocked/broken URL) - leave it hidden.
            return;
        }

        img.alt = `${destination} - travel destination photo`;
        img.classList.remove("hidden");
        caption.textContent = `📍 ${destination}`;
        caption.classList.remove("hidden");

    } catch (error) {
        // Decorative only - a failed lookup should never block showing the plan.
    }
}

function showResult(answer, threadId, startDate, endDate, destination) {
    latestAnswerMarkdown = answer;

    const resultSection = document.getElementById("resultSection");
    const resultBox = document.getElementById("resultBox");
    const threadInfo = document.getElementById("threadInfo");
    const pdfDates = document.getElementById("pdfDates");

    if (typeof marked !== "undefined") {
        resultBox.innerHTML = marked.parse(answer);
    } else {
        resultBox.innerText = answer;
    }

    // Open any links the AI included (hotel booking / Google Maps) in a new tab.
    resultBox.querySelectorAll("a").forEach((a) => {
        a.target = "_blank";
        a.rel = "noopener noreferrer";
    });

    addSectionIcons(resultBox);
    loadDestinationImage(destination);

    threadInfo.textContent = `Thread ID: ${threadId}`;

    if (startDate || endDate) {
        latestStartDate = startDate || "";
        latestEndDate = endDate || "";
        pdfDates.textContent = `Travel dates: ${formatDateLabel(startDate) || "-"} to ${formatDateLabel(endDate) || "-"}`;
        pdfDates.classList.remove("hidden");
    } else {
        pdfDates.classList.add("hidden");
        pdfDates.textContent = "";
    }

    resultSection.classList.remove("hidden");

    resultSection.scrollIntoView({
        behavior: "smooth",
        block: "start"
    });
}

function resetProgress() {
    const progressSection = document.getElementById("progressSection");
    const items = document.querySelectorAll("#progressList li");

    items.forEach((item) => item.classList.remove("done"));
    progressSection.classList.remove("hidden");
}

function markStageDone(stage) {
    const item = document.querySelector(`#progressList li[data-stage="${stage}"]`);

    if (item) {
        item.classList.add("done");
    }
}

function hideProgress() {
    document.getElementById("progressSection").classList.add("hidden");
}

function sendMessage() {
    hideError();

    const input = document.getElementById("userInput");
    const message = input.value.trim();
    const startDate = document.getElementById("startDate").value;
    const endDate = document.getElementById("endDate").value;

    if (!message) {
        showError("Please enter your travel request first.");
        return;
    }

    if (startDate && endDate && endDate < startDate) {
        showError("Return date can't be before the departure date.");
        return;
    }

    if (activeEventSource) {
        activeEventSource.close();
    }

    latestUserQuery = message;
    latestStartDate = startDate;
    latestEndDate = endDate;
    setLoading(true);
    resetProgress();

    const params = new URLSearchParams({ message: message });
    if (currentThreadId) {
        params.set("thread_id", currentThreadId);
    }
    if (startDate) {
        params.set("start_date", startDate);
    }
    if (endDate) {
        params.set("end_date", endDate);
    }

    const es = new EventSource(`/api/travel/stream?${params.toString()}`);
    activeEventSource = es;

    es.onmessage = (event) => {
        const data = JSON.parse(event.data);

        if (data.stage === "error") {
            showError(data.message || "Something went wrong.");
            es.close();
            activeEventSource = null;
            setLoading(false);
            hideProgress();
            return;
        }

        if (data.stage === "complete") {
            currentThreadId = data.thread_id;
            localStorage.setItem("travel_thread_id", currentThreadId);

            showResult(data.answer, data.thread_id, startDate, endDate, data.destination);

            es.close();
            activeEventSource = null;
            setLoading(false);
            hideProgress();
            return;
        }

        markStageDone(data.stage);
    };

    es.onerror = () => {
        if (activeEventSource) {
            showError("Connection to the server was lost. Please try again.");
            es.close();
            activeEventSource = null;
            setLoading(false);
            hideProgress();
        }
    };
}

function copyResult() {
    const resultBox = document.getElementById("resultBox");
    const text = resultBox.innerText;

    if (!text) {
        return;
    }

    navigator.clipboard.writeText(text)
        .then(() => {
            const copyBtn = document.querySelector(".copy-btn");
            const oldText = copyBtn.textContent;

            copyBtn.textContent = "Copied!";

            setTimeout(() => {
                copyBtn.textContent = oldText;
            }, 1400);
        })
        .catch(() => {
            showError("Could not copy result.");
        });
}

function waitForImages(container) {
    const images = Array.from(container.querySelectorAll("img")).filter((img) => !img.classList.contains("hidden"));

    return Promise.all(
        images.map((img) => {
            if (img.complete && img.naturalWidth) {
                return Promise.resolve();
            }

            return new Promise((resolve) => {
                img.onload = resolve;
                img.onerror = resolve;
            });
        })
    );
}

async function downloadPDF() {
    const pdfContent = document.getElementById("pdfContent");

    if (!latestAnswerMarkdown || !pdfContent) {
        showError("No travel plan available to download.");
        return;
    }

    const downloadBtn = document.querySelector(".download-btn");
    const oldText = downloadBtn.textContent;

    downloadBtn.textContent = "Preparing PDF...";
    downloadBtn.disabled = true;

    // html2canvas snapshots the page as it's currently displayed on screen -
    // it does not evaluate @media print rules - so the title/date subtitle
    // (hidden on screen) has to be shown explicitly before the snapshot.
    pdfContent.classList.add("pdf-exporting");

    await waitForImages(pdfContent);

    // "avoid-all" mode (tried previously) forces every possible element to
    // stay unbroken and can shove the ENTIRE first page's content down,
    // leaving a large blank gap above it. A targeted `avoid` list on just
    // headings/rows/images gives clean page breaks without that bug.
    const options = {
        margin: 0.5,
        filename: "ai-travel-plan.pdf",
        image: {
            type: "jpeg",
            quality: 0.98
        },
        html2canvas: {
            scale: 2,
            useCORS: true,
            backgroundColor: "#ffffff"
        },
        jsPDF: {
            unit: "in",
            format: "a4",
            orientation: "portrait"
        },
        pagebreak: {
            mode: ["css", "legacy"],
            avoid: ["h1", "h2", "h3", "tr", "li", "img", ".destination-image", ".destination-caption"]
        }
    };

    html2pdf()
        .set(options)
        .from(pdfContent)
        .save()
        .then(() => {
            downloadBtn.textContent = oldText;
            downloadBtn.disabled = false;
            pdfContent.classList.remove("pdf-exporting");
        })
        .catch(() => {
            downloadBtn.textContent = oldText;
            downloadBtn.disabled = false;
            pdfContent.classList.remove("pdf-exporting");
            showError("Could not download PDF.");
        });
}

document.addEventListener("keydown", function(event) {
    if (event.ctrlKey && event.key === "Enter") {
        sendMessage();
    }
});

// =========================
// Trip history
// =========================

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

async function toggleHistory() {
    const panel = document.getElementById("historyPanel");

    const opening = panel.classList.contains("hidden");
    panel.classList.toggle("hidden");

    if (opening) {
        await loadHistory();
    }
}

async function loadHistory() {
    const list = document.getElementById("historyList");
    const empty = document.getElementById("historyEmpty");

    try {
        const response = await fetch("/api/trips");
        const data = await response.json();

        if (!data.success) {
            throw new Error(data.error || "Could not load history.");
        }

        list.innerHTML = "";

        if (!data.trips.length) {
            empty.classList.remove("hidden");
            return;
        }

        empty.classList.add("hidden");

        data.trips.forEach((trip) => {
            const li = document.createElement("li");
            li.className = "history-item";
            li.onclick = () => openTrip(trip.id);

            const date = new Date(trip.created_at).toLocaleString();

            li.innerHTML = `
                <span class="history-item-query">${escapeHtml(trip.user_query.slice(0, 80))}</span>
                <span class="history-item-date">${escapeHtml(date)}</span>
            `;

            list.appendChild(li);
        });

    } catch (error) {
        showError(error.message);
    }
}

async function openTrip(tripId) {
    try {
        const response = await fetch(`/api/trips/${tripId}`);
        const data = await response.json();

        if (!data.success) {
            throw new Error(data.error || "Could not load this trip.");
        }

        const trip = data.trip;

        currentThreadId = trip.thread_id;
        latestUserQuery = trip.user_query;
        localStorage.setItem("travel_thread_id", currentThreadId);

        showResult(trip.answer, trip.thread_id, null, null, trip.destination);

        document.getElementById("historyPanel").classList.add("hidden");

    } catch (error) {
        showError(error.message);
    }
}

// =========================
// Add to calendar (.ics)
// =========================

function guessTripDays(query) {
    const match = query.match(/(\d+)\s*[-\s]?\s*day/i);
    return match ? parseInt(match[1], 10) : 3;
}

function foldIcsLine(line) {
    // RFC 5545 recommends folding lines longer than ~75 octets.
    const chunks = [];
    let rest = line;

    while (rest.length > 74) {
        chunks.push(rest.slice(0, 74));
        rest = " " + rest.slice(74);
    }

    chunks.push(rest);
    return chunks.join("\r\n");
}

function escapeIcsText(text) {
    return text
        .replace(/\\/g, "\\\\")
        .replace(/;/g, "\\;")
        .replace(/,/g, "\\,")
        .replace(/\r?\n/g, "\\n");
}

function formatIcsDate(date) {
    const y = date.getFullYear();
    const m = String(date.getMonth() + 1).padStart(2, "0");
    const d = String(date.getDate()).padStart(2, "0");
    return `${y}${m}${d}`;
}

function downloadCalendar() {
    if (!latestAnswerMarkdown) {
        showError("No travel plan available to add to a calendar.");
        return;
    }

    const startInput = prompt("Trip start date (YYYY-MM-DD):", latestStartDate || new Date().toISOString().slice(0, 10));

    if (!startInput) {
        return;
    }

    const startDate = new Date(startInput);

    if (isNaN(startDate.getTime())) {
        showError("That doesn't look like a valid date (use YYYY-MM-DD).");
        return;
    }

    let endDate;
    if (latestEndDate) {
        endDate = new Date(latestEndDate);
    }
    if (!latestEndDate || isNaN(endDate.getTime())) {
        const days = guessTripDays(latestUserQuery || "");
        endDate = new Date(startDate);
        endDate.setDate(endDate.getDate() + days);
    }

    const summary = escapeIcsText(`Trip: ${latestUserQuery || "Roamly trip"}`);
    const description = escapeIcsText(latestAnswerMarkdown);
    const stamp = formatIcsDate(new Date()) + "T000000Z";

    const lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Roamly//Trip Planner//EN",
        "BEGIN:VEVENT",
        `UID:${Date.now()}@roamly`,
        `DTSTAMP:${stamp}`,
        `DTSTART;VALUE=DATE:${formatIcsDate(startDate)}`,
        `DTEND;VALUE=DATE:${formatIcsDate(endDate)}`,
        foldIcsLine(`SUMMARY:${summary}`),
        foldIcsLine(`DESCRIPTION:${description}`),
        "END:VEVENT",
        "END:VCALENDAR"
    ];

    const icsContent = lines.join("\r\n");
    const blob = new Blob([icsContent], { type: "text/calendar" });
    const url = URL.createObjectURL(blob);

    const link = document.createElement("a");
    link.href = url;
    link.download = "roamly-trip.ics";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);

    URL.revokeObjectURL(url);
}