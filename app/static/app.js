(function () {
  function bindDeleteConfirm() {
    var buttons = document.getElementsByClassName("js-confirm-delete");
    var i;
    for (i = 0; i < buttons.length; i += 1) {
      buttons[i].onclick = function () {
        return window.confirm("Er du sikker på, at denne DJ skal slettes?");
      };
    }
  }

  function bindVolumeSlider() {
    var range = document.getElementById("volume-range");
    var value = document.getElementById("volume-value");
    if (!range || !value) {
      return;
    }
    function sync() {
      value.innerHTML = String(range.value) + "x";
    }
    range.oninput = sync;
    range.onchange = sync;
    sync();
  }

  function updateStatusView(data) {
    var stateNode = document.getElementById("status-state");
    var volumeValue = document.getElementById("volume-value");
    var volumeRange = document.getElementById("volume-range");
    if (!stateNode || !data) {
      return;
    }
    document.getElementById("status-active").innerHTML = data.active_channel || "Ingen valgt";
    stateNode.innerHTML = data.source_state;
    stateNode.className = "state state-" + data.source_state;
    document.getElementById("status-running").innerHTML = data.stream_running ? "Ja" : "Nej";
    document.getElementById("status-listeners").innerHTML = String(data.listeners);
    document.getElementById("status-uptime").innerHTML = String(data.uptime_seconds) + " sek.";
    document.getElementById("status-error").innerHTML = data.last_error || "Ingen";
    document.getElementById("status-streamlink-pid").innerHTML = data.streamlink_pid || "-";
    document.getElementById("status-ffmpeg-pid").innerHTML = data.ffmpeg_pid || "-";
    document.getElementById("status-usage").innerHTML =
      (data.cpu_percent !== null ? data.cpu_percent : "-") +
      " % / " +
      (data.memory_mb !== null ? data.memory_mb : "-") +
      " MB";
    if (volumeValue && volumeRange && data.stream_volume !== undefined) {
      volumeRange.value = String(data.stream_volume);
      volumeValue.innerHTML = String(data.stream_volume) + "x";
    }
  }

  function pollStatus() {
    var xhr = new XMLHttpRequest();
    xhr.open("GET", "/api/status", true);
    xhr.onreadystatechange = function () {
      if (xhr.readyState === 4 && xhr.status === 200) {
        try {
          updateStatusView(JSON.parse(xhr.responseText));
        } catch (e) {
        }
      }
    };
    xhr.send(null);
  }

  bindDeleteConfirm();
  bindVolumeSlider();
  window.setInterval(pollStatus, 10000);
}());
