(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const IMAGE_EXT = ["png", "jpg", "jpeg", "tif", "tiff", "bmp", "webp", "gif"];
  const XML_EXT = ["mxl", "musicxml", "xml"];
  const POLL_MS = 2000;

  const state = { files: [], jobId: null, timer: null, synth: null, visualObj: null, baseName: "score" };

  const ext = (name) => (name.split(".").pop() || "").toLowerCase();

  // ------------------------------------------------------------------ files
  function addFiles(list) {
    hideError();
    for (const f of list) {
      const e = ext(f.name);
      if (![...IMAGE_EXT, "pdf", ...XML_EXT].includes(e)) {
        showError(`“${f.name}” is not a supported file. Use PDF, PNG, JPG, TIFF or MusicXML.`);
        continue;
      }
      state.files.push({ file: f, url: IMAGE_EXT.includes(e) && e !== "tif" && e !== "tiff" ? URL.createObjectURL(f) : null });
    }
    renderFiles();
  }

  function renderFiles() {
    const ol = $("file-list");
    ol.innerHTML = "";
    state.files.forEach((item, i) => {
      const li = document.createElement("li");
      const thumb = document.createElement("div");
      thumb.className = "thumb";
      if (item.url) {
        const img = document.createElement("img");
        img.src = item.url;
        img.alt = `Page ${i + 1}`;
        thumb.appendChild(img);
      } else {
        const d = document.createElement("span");
        d.className = "doc";
        d.textContent = ext(item.file.name).toUpperCase();
        thumb.appendChild(d);
      }
      const meta = document.createElement("div");
      meta.className = "file-meta";
      const name = document.createElement("span");
      name.textContent = `${i + 1}. ${item.file.name}`;
      name.title = item.file.name;
      meta.append(name,
        iconBtn("◀", "Move earlier", i === 0, () => move(i, -1)),
        iconBtn("▶", "Move later", i === state.files.length - 1, () => move(i, 1)),
        iconBtn("✕", "Remove", false, () => remove(i)));
      li.append(thumb, meta);
      ol.appendChild(li);
    });
    ol.hidden = state.files.length === 0;
    $("convert-btn").disabled = state.files.length === 0;
    $("clear-btn").hidden = state.files.length === 0;
  }

  function iconBtn(label, title, disabled, onClick) {
    const b = document.createElement("button");
    b.className = "icon-btn";
    b.type = "button";
    b.textContent = label;
    b.title = title;
    b.setAttribute("aria-label", title);
    b.disabled = disabled;
    b.addEventListener("click", (ev) => { ev.preventDefault(); onClick(); });
    return b;
  }

  function move(i, d) {
    const [it] = state.files.splice(i, 1);
    state.files.splice(i + d, 0, it);
    renderFiles();
  }

  function remove(i) {
    const [it] = state.files.splice(i, 1);
    if (it.url) URL.revokeObjectURL(it.url);
    renderFiles();
  }

  function clearFiles() {
    state.files.forEach((it) => it.url && URL.revokeObjectURL(it.url));
    state.files = [];
    renderFiles();
    hideError();
  }

  // ------------------------------------------------------------------ status
  function showStatus(text, sub = "") {
    $("status").hidden = false;
    $("status-text").textContent = text;
    $("status-sub").textContent = sub;
  }
  const hideStatus = () => { $("status").hidden = true; };

  function showError(msg, log) {
    $("error").hidden = false;
    $("error-text").textContent = msg;
    $("error-log-wrap").hidden = !log;
    $("error-log").textContent = log || "";
  }
  const hideError = () => { $("error").hidden = true; };

  function busy(on) {
    $("convert-btn").disabled = on || state.files.length === 0;
    $("convert-btn").textContent = on ? "Converting…" : "Convert to ABC";
  }

  async function readError(res) {
    try {
      const j = await res.json();
      return j.error || j.detail || res.statusText;
    } catch {
      return `${res.status} ${res.statusText}`;
    }
  }

  // ------------------------------------------------------------------ convert
  async function convert() {
    hideError();
    if (!state.files.length) return;
    const xml = state.files.filter((f) => XML_EXT.includes(ext(f.file.name)));
    state.baseName = state.files[0].file.name.replace(/\.[^.]+$/, "").replace(/^\d+_/, "") || "score";
    busy(true);
    try {
      if (xml.length) {
        if (state.files.length > 1) throw new Error("Upload a MusicXML file on its own.");
        showStatus("Converting MusicXML…");
        const fd = new FormData();
        fd.append("file", xml[0].file);
        const res = await fetch("api/musicxml", { method: "POST", body: fd });
        if (!res.ok) throw new Error(await readError(res));
        const j = await res.json();
        hideStatus();
        showResult(j.abc, []);
        busy(false);
        return;
      }
      showStatus("Uploading…");
      const fd = new FormData();
      state.files.forEach((f) => fd.append("files", f.file));
      const res = await fetch("api/jobs", { method: "POST", body: fd });
      if (!res.ok) throw new Error(await readError(res));
      const job = await res.json();
      state.jobId = job.id;
      onJob(job);
    } catch (err) {
      hideStatus();
      busy(false);
      showError(err.message || String(err));
    }
  }

  function onJob(job) {
    if (job.status === "queued") {
      showStatus("Waiting in line…", job.position > 1 ? `${job.position - 1} score(s) ahead of yours` : "Starting soon");
    } else if (job.status === "running") {
      showStatus("Reading the music…", `${Math.round(job.elapsed)} s — usually 20–60 s per page`);
    } else if (job.status === "done") {
      hideStatus();
      busy(false);
      showResult(job.abc, job.musicxml);
      return;
    } else if (job.status === "error") {
      hideStatus();
      busy(false);
      showError(job.error || "Conversion failed.", job.log);
      return;
    }
    clearTimeout(state.timer);
    state.timer = setTimeout(poll, POLL_MS);
  }

  async function poll() {
    try {
      const res = await fetch(`api/jobs/${state.jobId}`);
      if (!res.ok) throw new Error(await readError(res));
      onJob(await res.json());
    } catch (err) {
      hideStatus();
      busy(false);
      showError(`Lost track of the conversion: ${err.message}`);
    }
  }

  // ------------------------------------------------------------------ result
  function showResult(abc, xmlFiles) {
    $("result").hidden = false;
    $("abc-text").value = abc;
    const link = $("dl-xml");
    if (xmlFiles && xmlFiles.length && state.jobId) {
      link.hidden = false;
      link.href = `api/jobs/${state.jobId}/musicxml/0`;
      link.setAttribute("download", xmlFiles[0]);
    } else {
      link.hidden = true;
    }
    render();
    $("result").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  let renderTimer = null;
  function scheduleRender() {
    clearTimeout(renderTimer);
    renderTimer = setTimeout(render, 350);
  }

  function render() {
    const abc = $("abc-text").value;
    const width = Math.max(320, $("paper").clientWidth - 16);
    const visual = ABCJS.renderAbc("paper", abc, {
      responsive: "resize",
      staffwidth: Math.min(width, 900),
      add_classes: true,
      wrap: { minSpacing: 1.6, maxSpacing: 2.7, preferredMeasuresPerLine: 4 },
    });
    state.visualObj = visual[0];
    const warnings = (visual[0] && visual[0].warnings) || [];
    $("abc-warn").textContent = warnings.length ? `${warnings.length} syntax warning${warnings.length > 1 ? "s" : ""}` : "";
    $("abc-warn").title = warnings.map((w) => w.replace(/<[^>]+>/g, "")).join("\n");
    setupAudio();
  }

  async function setupAudio() {
    if (!ABCJS.synth.supportsAudio()) {
      $("audio").textContent = "Audio playback is not supported in this browser.";
      return;
    }
    if (!state.synth) {
      state.synth = new ABCJS.synth.SynthController();
      state.synth.load("#audio", cursorControl(), {
        displayLoop: true, displayRestart: true, displayPlay: true, displayProgress: true, displayWarp: true,
      });
    }
    try {
      await state.synth.setTune(state.visualObj, false, {});
    } catch (err) {
      console.warn("Audio problem:", err);
    }
  }

  function cursorControl() {
    return {
      onEvent(ev) {
        document.querySelectorAll("#paper .abcjs-highlight").forEach((el) => el.classList.remove("abcjs-highlight"));
        (ev.elements || []).flat().forEach((el) => el.classList.add("abcjs-highlight"));
      },
      onFinished() {
        document.querySelectorAll("#paper .abcjs-highlight").forEach((el) => el.classList.remove("abcjs-highlight"));
      },
    };
  }

  function download(blob, name) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  }

  // ------------------------------------------------------------------ sample
  async function loadSample() {
    try {
      const res = await fetch("samples/sample.png");
      if (!res.ok) throw new Error("sample not found");
      const blob = await res.blob();
      clearFiles();
      addFiles([new File([blob], "sample.png", { type: "image/png" })]);
      $("upload-card").scrollIntoView({ behavior: "smooth" });
    } catch (err) {
      showError(`Could not load the sample: ${err.message}`);
    }
  }

  // ------------------------------------------------------------------ wiring
  const dz = $("dropzone");
  ["dragenter", "dragover"].forEach((t) => dz.addEventListener(t, (e) => { e.preventDefault(); dz.classList.add("over"); }));
  ["dragleave", "drop"].forEach((t) => dz.addEventListener(t, (e) => { e.preventDefault(); dz.classList.remove("over"); }));
  dz.addEventListener("drop", (e) => addFiles(e.dataTransfer.files));
  dz.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("file-input").click(); } });
  $("file-input").addEventListener("change", (e) => { addFiles(e.target.files); e.target.value = ""; });
  document.addEventListener("paste", (e) => {
    const files = [...(e.clipboardData?.files || [])];
    if (files.length && !e.target.closest("textarea")) addFiles(files);
  });
  $("convert-btn").addEventListener("click", convert);
  $("clear-btn").addEventListener("click", clearFiles);
  $("sample-btn").addEventListener("click", loadSample);
  $("abc-text").addEventListener("input", scheduleRender);
  $("copy-btn").addEventListener("click", async () => {
    await navigator.clipboard.writeText($("abc-text").value);
    $("copy-btn").textContent = "Copied";
    setTimeout(() => { $("copy-btn").textContent = "Copy ABC"; }, 1500);
  });
  $("dl-abc").addEventListener("click", () => {
    download(new Blob([$("abc-text").value], { type: "text/vnd.abc" }), `${state.baseName}.abc`);
  });
  $("dl-midi").addEventListener("click", () => {
    const midi = ABCJS.synth.getMidiFile($("abc-text").value, { midiOutputType: "binary" });
    if (midi && midi[0]) download(new Blob([midi[0]], { type: "audio/midi" }), `${state.baseName}.mid`);
  });
  window.addEventListener("resize", () => state.visualObj && scheduleRender());

  fetch("api/health").then((r) => r.json()).then((h) => {
    if (!h.omr) {
      showError("Image and PDF recognition is not available on this server right now. MusicXML files still convert.");
    }
  }).catch(() => {});
})();
