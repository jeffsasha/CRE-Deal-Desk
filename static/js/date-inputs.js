// Keep the submitted ISO value separate from the calendar's browser-independent UI.
export function parseDateInput(value, kind) {
  const text = value.trim();
  const time = kind === "time";
  const match = text.match(time ? /^(\d{2}):(\d{2})$/ : kind === "datetime-local" ?
    /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})$/ : /^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return null;
  const year = time ? 2000 : Number(match[1]);
  const month = time ? 1 : Number(match[2]);
  const day = time ? 1 : Number(match[3]);
  const hour = time ? Number(match[1]) : Number(match[4] || 0);
  const minute = time ? Number(match[2]) : Number(match[5] || 0);
  if (year < 1 || month < 1 || month > 12 || day < 1 || day > 31 || hour > 23 || minute > 59) return null;
  const result = new Date(2000, 0, 1, hour, minute, 0, 0);
  result.setFullYear(year, month - 1, day);
  return result.getFullYear() === year && result.getMonth() + 1 === month && result.getDate() === day ? result : null;
}

if (typeof document !== "undefined" && window.flatpickr) {
  const zh = document.documentElement.lang.startsWith("zh");
  const controls = new Set();
  const locale = zh ? {...window.flatpickr.l10ns.zh, yearAriaLabel: "年份", monthAriaLabel: "月份", hourAriaLabel: "小时", minuteAriaLabel: "分钟"} : "en";

  function validate(input) {
    if (input.disabled) return true;
    const date = input.value.trim() ? parseDateInput(input.value, input.dataset.dateKind) : null;
    let valid = !input.value.trim() || !!date;
    const min = input.getAttribute("min"), max = input.getAttribute("max");
    if (date && min) valid = valid && date >= parseDateInput(min, input.dataset.dateKind);
    if (date && max) valid = valid && date <= parseDateInput(max, input.dataset.dateKind);
    input.setCustomValidity(valid ? "" : (zh ? "请输入有效日期或时间，格式：" : "Enter a valid date or time in this format: ") + input.placeholder);
    return valid;
  }

  function enhance(scope) {
    scope.querySelectorAll('input[type="date"], input[type="datetime-local"], input[type="time"]').forEach(input => {
      const kind = input.type, initial = input.value;
      const format = kind === "time" ? "H:i" : kind === "datetime-local" ? "Y-m-d H:i" : "Y-m-d";
      input.type = "text";
      input.dataset.dateKind = kind;
      input.value = initial.replace("T", " ");
      input.placeholder = kind === "time" ? "HH:MM" : kind === "datetime-local" ? "YYYY-MM-DD HH:MM" : "YYYY-MM-DD";
      input.autocomplete = "off";
      const wrapper = document.createElement("span");
      wrapper.className = "date-control";
      input.before(wrapper);
      wrapper.appendChild(input);
      const button = document.createElement("button"), proxy = document.createElement("input");
      button.type = "button";
      button.className = "date-control-open";
      const label = kind === "time" ? (zh ? "选择时间" : "Choose time") : (zh ? "选择日期" : "Choose date");
      button.setAttribute("aria-label", label + (input.labels.length ? ": " + input.labels[0].textContent.trim() : ""));
      button.title = label;
      button.innerHTML = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 11h18"/></svg>';
      proxy.hidden = true;
      proxy.tabIndex = -1;
      wrapper.append(button, proxy);
      // Only this unnamed hidden input is controlled by the picker. Manual text is
      // never normalized, silently cleared, or moved to another day by the library.
      const picker = window.flatpickr(proxy, {
        locale, dateFormat: format, ariaDateFormat: zh ? "Y年n月j日" : "F j, Y", disableMobile: true, clickOpens: false,
        enableTime: kind !== "date", noCalendar: kind === "time", time_24hr: true, minuteIncrement: 1,
        positionElement: input, defaultDate: parseDateInput(initial, kind) || undefined,
        appendTo: document.body.hasAttribute("data-editor-page") ? wrapper : undefined,
        minDate: input.min ? parseDateInput(input.min, kind) : undefined,
        maxDate: input.max ? parseDateInput(input.max, kind) : undefined,
        onChange(dates, value) {
          if (!dates.length) return;
          input.value = value;
          validate(input);
          input.dispatchEvent(new Event("input", {bubbles: true}));
          input.dispatchEvent(new Event("change", {bubbles: true}));
        }
      });
      picker.calendarContainer.setAttribute("role", "dialog");
      picker.calendarContainer.setAttribute("aria-label", label);
      button.setAttribute("aria-haspopup", "dialog");
      button.addEventListener("click", () => {
        if (input.disabled || input.readOnly) return;
        const value = parseDateInput(input.value, kind);
        if (value) picker.setDate(value, false); else picker.clear(false);
        picker.open();
        const focus = kind === "time" ? picker.hourElement : picker.selectedDateElem || picker.todayDateElem || picker.calendarContainer.querySelector(".flatpickr-day:not(.flatpickr-disabled)");
        if (focus) focus.focus();
      });
      input.addEventListener("input", () => validate(input));
      input.addEventListener("blur", () => validate(input));
      validate(input);
      controls.add({picker, input, button});
    });
  }
  document.addEventListener("submit", event => {
    const invalid = [...event.target.querySelectorAll("[data-date-kind]")].find(input => !validate(input));
    if (invalid) { event.preventDefault(); event.stopImmediatePropagation(); invalid.reportValidity(); }
  }, true);
  document.addEventListener("keydown", event => {
    if (event.key !== "Escape") return;
    const open = [...controls].find(control => control.picker.isOpen);
    if (open) {
      event.preventDefault(); event.stopImmediatePropagation();
      open.picker.close(); open.button.focus({preventScroll: true});
    }
  }, true);
  document.addEventListener("workspace:before", () => { controls.forEach(control => control.picker.destroy()); controls.clear(); });
  document.addEventListener("workspace:content", event => enhance(event.detail));
  enhance(document);
}
