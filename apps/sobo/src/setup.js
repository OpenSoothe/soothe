(() => {
  const bridge = window.soboSetup;
  document.documentElement.dataset.platform = bridge?.platform ?? "browser";

  const form = document.getElementById("setup");
  const serverUrl = document.getElementById("server-url");
  const status = document.getElementById("status");
  const checkButton = document.getElementById("check");
  const continueButton = document.getElementById("continue");
  const quitButton = document.getElementById("quit");

  // Pre-fill default if available.
  bridge?.state().then(state => {
    if (state.saved?.serverUrl) serverUrl.value = state.saved.serverUrl;
    else if (state.defaultLocalUrl) serverUrl.value = state.defaultLocalUrl;
  });

  function setStatus(message, tone) {
    status.textContent = message;
    if (tone === undefined) status.removeAttribute("data-tone");
    else status.setAttribute("data-tone", tone);
  }

  function setBusy(busy) {
    checkButton.disabled = busy;
    continueButton.disabled = busy;
  }

  async function check() {
    const value = serverUrl.value;
    if (value.trim() === "") {
      setStatus("Enter a server address first.", "error");
      return null;
    }
    setBusy(true);
    setStatus("Checking…");
    try {
      const result = await bridge.test(value);
      if (result.ok) {
        serverUrl.value = result.url;
        setStatus(`Soothe Bridge answered at ${result.url}.`, "ok");
      } else {
        setStatus(result.error ?? "Could not reach that address.", "error");
      }
      return result;
    } catch {
      setStatus("Could not run the connection check.", "error");
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    setBusy(true);
    setStatus("Connecting…");
    try {
      const result = await bridge.save({ serverUrl: serverUrl.value });
      if (!result.ok) {
        setStatus(result.error ?? "Could not save that address.", "error");
      }
    } catch {
      setStatus("Could not save. Try again.", "error");
    } finally {
      setBusy(false);
    }
  }

  checkButton.addEventListener("click", () => void check());

  form.addEventListener("submit", e => {
    e.preventDefault();
    void (async () => {
      const result = await check();
      if (result?.ok) await save();
    })();
  });

  quitButton.addEventListener("click", () => bridge?.quit());
})();
