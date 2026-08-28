(function () {
  'use strict';

  var toastTypeConfig = {
    success: {label: '成功', icon: '✓', delay: 3000},
    error: {label: '错误', icon: '!', delay: 6000},
    warning: {label: '警告', icon: '!', delay: 5000},
    info: {label: '提示', icon: 'i', delay: 4000}
  };
  var activeDialogResolver = null;
  var activeDialogResult = false;
  var comboboxInstances = [];
  var commonHeaderOptions = [
    'Accept',
    'Accept-Encoding',
    'Authorization',
    'Cache-Control',
    'Connection',
    'Content-Type',
    'Cookie',
    'Origin',
    'User-Agent',
    'X-Request-Id'
  ];

  function normalizeOptions(options, defaults) {
    if (typeof options === 'string') {
      return Object.assign({}, defaults, {message: options});
    }
    return Object.assign({}, defaults, options || {});
  }

  function showToast(message, type, options) {
    var normalizedType = toastTypeConfig[type] ? type : 'info';
    var config = toastTypeConfig[normalizedType];
    var settings = Object.assign({delay: config.delay, autohide: true}, options || {});
    var container = document.getElementById('appToastContainer');
    if (!container) return null;

    var toastElement = document.createElement('div');
    toastElement.className = 'toast app-toast-' + normalizedType;
    toastElement.setAttribute('role', normalizedType === 'error' ? 'alert' : 'status');
    toastElement.setAttribute('aria-live', normalizedType === 'error' ? 'assertive' : 'polite');
    toastElement.setAttribute('aria-atomic', 'true');

    var toastBody = document.createElement('div');
    toastBody.className = 'toast-body d-flex align-items-start gap-3 py-3';
    var icon = document.createElement('span');
    icon.className = 'app-toast-icon';
    icon.setAttribute('aria-hidden', 'true');
    icon.textContent = config.icon;
    var content = document.createElement('div');
    content.className = 'flex-grow-1';
    var title = document.createElement('div');
    title.className = 'fw-semibold mb-1';
    title.textContent = settings.title || config.label;
    var messageElement = document.createElement('div');
    messageElement.className = 'app-toast-message small text-secondary';
    messageElement.textContent = String(message || '');
    var closeButton = document.createElement('button');
    closeButton.type = 'button';
    closeButton.className = 'btn-close ms-1';
    closeButton.setAttribute('data-bs-dismiss', 'toast');
    closeButton.setAttribute('aria-label', '关闭');

    content.appendChild(title);
    content.appendChild(messageElement);
    toastBody.appendChild(icon);
    toastBody.appendChild(content);
    toastBody.appendChild(closeButton);
    toastElement.appendChild(toastBody);
    container.appendChild(toastElement);

    toastElement.addEventListener('hidden.bs.toast', function () {
      toastElement.remove();
    }, {once: true});
    var toast = new bootstrap.Toast(toastElement, {
      autohide: settings.autohide,
      delay: settings.delay
    });
    toast.show();
    return toast;
  }

  function dialogElements() {
    return {
      modal: document.getElementById('appDialogModal'),
      title: document.getElementById('appDialogTitle'),
      message: document.getElementById('appDialogMessage'),
      icon: document.getElementById('appDialogIcon'),
      cancelButton: document.getElementById('appDialogCancelButton'),
      confirmButton: document.getElementById('appDialogConfirmButton')
    };
  }

  function finishDialog(result) {
    activeDialogResult = result;
    var elements = dialogElements();
    bootstrap.Modal.getOrCreateInstance(elements.modal).hide();
  }

  function showDialog(options, alertOnly) {
    var settings = normalizeOptions(options, {
      title: alertOnly ? '提示' : '操作确认',
      message: '',
      confirmText: alertOnly ? '我知道了' : '确认',
      cancelText: '取消',
      tone: 'primary'
    });
    var elements = dialogElements();
    if (!elements.modal) return Promise.resolve(false);

    if (activeDialogResolver) {
      activeDialogResolver(false);
      activeDialogResolver = null;
    }
    activeDialogResult = false;
    elements.title.textContent = settings.title;
    elements.message.textContent = settings.message;
    elements.cancelButton.textContent = settings.cancelText;
    elements.cancelButton.classList.toggle('d-none', alertOnly);
    elements.confirmButton.textContent = settings.confirmText;
    elements.confirmButton.className = 'btn btn-' + (settings.tone === 'danger' ? 'danger' : settings.tone === 'warning' ? 'warning' : 'primary');
    elements.icon.className = 'app-dialog-icon' + (settings.tone === 'danger' ? ' app-dialog-danger' : settings.tone === 'warning' ? ' app-dialog-warning' : '');
    elements.icon.textContent = alertOnly ? 'i' : '!';

    var modal = bootstrap.Modal.getOrCreateInstance(elements.modal);
    modal.show();
    return new Promise(function (resolve) {
      activeDialogResolver = resolve;
    });
  }

  function normalizeComboboxOptions(options) {
    return (options || []).map(function (item) {
      if (typeof item === 'string') return {value: item, label: item};
      return {
        value: String(item.value == null ? '' : item.value),
        label: String(item.label == null ? item.value : item.label),
        description: String(item.description || '')
      };
    }).filter(function (item) { return item.value; });
  }

  function closeOtherComboboxes(current) {
    comboboxInstances.forEach(function (instance) {
      if (instance !== current) instance.close();
    });
  }

  function attachCombobox(input, options) {
    if (!input) return null;
    if (input._appCombobox) {
      input._appCombobox.setOptions((options || {}).options || []);
      return input._appCombobox;
    }
    var settings = Object.assign({
      options: [],
      allowCustom: false,
      emptyText: '暂无匹配选项',
      customText: '直接使用'
    }, options || {});
    var wrapper = document.createElement('div');
    wrapper.className = 'app-combobox';
    input.parentNode.insertBefore(wrapper, input);
    wrapper.appendChild(input);
    input.classList.add('app-combobox-input');
    input.setAttribute('autocomplete', 'off');
    input.setAttribute('role', 'combobox');
    input.setAttribute('aria-autocomplete', 'list');
    input.setAttribute('aria-expanded', 'false');

    var toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'app-combobox-toggle';
    toggle.setAttribute('aria-label', '展开选项');
    toggle.innerHTML = '<span aria-hidden="true">⌄</span>';
    wrapper.appendChild(toggle);

    var menu = document.createElement('div');
    menu.className = 'app-combobox-menu';
    menu.setAttribute('role', 'listbox');
    document.body.appendChild(menu);
    var normalizedOptions = normalizeComboboxOptions(settings.options);
    var activeIndex = -1;
    var visibleItems = [];

    function positionMenu() {
      if (!menu.classList.contains('show')) return;
      var rect = wrapper.getBoundingClientRect();
      menu.style.left = rect.left + 'px';
      menu.style.top = (rect.bottom + 6) + 'px';
      menu.style.width = Math.max(rect.width, 220) + 'px';
    }

    function setActive(index) {
      activeIndex = visibleItems.length ? Math.max(0, Math.min(index, visibleItems.length - 1)) : -1;
      visibleItems.forEach(function (item, itemIndex) {
        item.classList.toggle('active', itemIndex === activeIndex);
      });
      if (activeIndex >= 0) visibleItems[activeIndex].scrollIntoView({block: 'nearest'});
    }

    function selectValue(value) {
      input.value = value;
      input.dispatchEvent(new Event('input', {bubbles: true}));
      input.dispatchEvent(new Event('change', {bubbles: true}));
      controller.close();
      input.focus();
    }

    function render() {
      var keyword = String(input.value || '').trim().toLowerCase();
      var filtered = normalizedOptions.filter(function (item) {
        return !keyword || item.label.toLowerCase().indexOf(keyword) >= 0 || item.value.toLowerCase().indexOf(keyword) >= 0;
      });
      menu.innerHTML = '';
      filtered.forEach(function (item) {
        var button = document.createElement('button');
        button.type = 'button';
        button.className = 'app-combobox-option';
        button.setAttribute('role', 'option');
        var label = document.createElement('span');
        label.className = 'app-combobox-option-label';
        label.textContent = item.label;
        button.appendChild(label);
        if (item.description) {
          var description = document.createElement('span');
          description.className = 'app-combobox-option-description';
          description.textContent = item.description;
          button.appendChild(description);
        }
        button.addEventListener('mousedown', function (event) { event.preventDefault(); });
        button.addEventListener('click', function () { selectValue(item.value); });
        menu.appendChild(button);
      });
      if (settings.allowCustom && keyword && !normalizedOptions.some(function (item) { return item.value.toLowerCase() === keyword; })) {
        var customButton = document.createElement('button');
        customButton.type = 'button';
        customButton.className = 'app-combobox-option app-combobox-custom';
        customButton.textContent = settings.customText + '“' + input.value.trim() + '”';
        customButton.addEventListener('mousedown', function (event) { event.preventDefault(); });
        customButton.addEventListener('click', function () { selectValue(input.value.trim()); });
        menu.appendChild(customButton);
      }
      if (!menu.children.length) {
        var empty = document.createElement('div');
        empty.className = 'app-combobox-empty';
        empty.textContent = settings.emptyText;
        menu.appendChild(empty);
      }
      visibleItems = Array.prototype.slice.call(menu.querySelectorAll('.app-combobox-option'));
      activeIndex = -1;
      positionMenu();
    }

    function onInput() { controller.open(); }
    function onKeydown(event) {
      if (event.key === 'ArrowDown') { event.preventDefault(); if (!menu.classList.contains('show')) controller.open(); setActive(activeIndex + 1); }
      else if (event.key === 'ArrowUp') { event.preventDefault(); setActive(activeIndex <= 0 ? visibleItems.length - 1 : activeIndex - 1); }
      else if (event.key === 'Enter' && activeIndex >= 0) { event.preventDefault(); visibleItems[activeIndex].click(); }
      else if (event.key === 'Escape') controller.close();
    }
    function onToggle() {
      if (menu.classList.contains('show')) controller.close();
      else { input.focus(); controller.open(); }
    }
    function onDocumentMouseDown(event) {
      if (!wrapper.contains(event.target) && !menu.contains(event.target)) controller.close();
    }

    var controller = {
      open: function () {
        closeOtherComboboxes(controller);
        render();
        menu.classList.add('show');
        input.setAttribute('aria-expanded', 'true');
        wrapper.classList.add('open');
        positionMenu();
      },
      close: function () {
        menu.classList.remove('show');
        input.setAttribute('aria-expanded', 'false');
        wrapper.classList.remove('open');
        activeIndex = -1;
      },
      setOptions: function (items) {
        normalizedOptions = normalizeComboboxOptions(items);
        if (menu.classList.contains('show')) render();
      },
      destroy: function () {
        controller.close();
        input.removeEventListener('focus', controller.open);
        input.removeEventListener('input', onInput);
        input.removeEventListener('keydown', onKeydown);
        toggle.removeEventListener('click', onToggle);
        document.removeEventListener('mousedown', onDocumentMouseDown);
        window.removeEventListener('resize', positionMenu);
        window.removeEventListener('scroll', positionMenu, true);
        menu.remove();
        input._appCombobox = null;
        comboboxInstances = comboboxInstances.filter(function (instance) { return instance !== controller; });
      }
    };

    input.addEventListener('focus', controller.open);
    input.addEventListener('input', onInput);
    input.addEventListener('keydown', onKeydown);
    toggle.addEventListener('click', onToggle);
    document.addEventListener('mousedown', onDocumentMouseDown);
    window.addEventListener('resize', positionMenu);
    window.addEventListener('scroll', positionMenu, true);
    input._appCombobox = controller;
    comboboxInstances.push(controller);
    return controller;
  }

  function destroyComboboxesWithin(root) {
    if (!root || !root.querySelectorAll) return;
    Array.prototype.forEach.call(root.querySelectorAll('.app-combobox-input'), function (input) {
      if (input._appCombobox) input._appCombobox.destroy();
    });
  }

  function disableBrowserInputHistory(root) {
    var scope = root && root.querySelectorAll ? root : document;
    scope.querySelectorAll('input:not([type]), input[type="text"], input[type="url"], input[type="search"], input[type="email"]').forEach(function (input) {
      if (!input.hasAttribute('autocomplete')) input.setAttribute('autocomplete', 'off');
    });
  }

  var elements = dialogElements();
  if (elements.confirmButton) {
    elements.confirmButton.addEventListener('click', function () {
      finishDialog(true);
    });
    elements.modal.addEventListener('shown.bs.modal', function () {
      elements.confirmButton.focus();
    });
    elements.modal.addEventListener('hidden.bs.modal', function () {
      if (activeDialogResolver) {
        activeDialogResolver(activeDialogResult);
        activeDialogResolver = null;
      }
      activeDialogResult = false;
    });
  }

  window.AppToast = {
    show: showToast,
    success: function (message, options) { return showToast(message, 'success', options); },
    error: function (message, options) { return showToast(message, 'error', options); },
    warning: function (message, options) { return showToast(message, 'warning', options); },
    info: function (message, options) { return showToast(message, 'info', options); }
  };
  window.AppDialog = {
    confirm: function (options) { return showDialog(options, false); },
    alert: function (options) { return showDialog(options, true); }
  };
  window.AppCombobox = {
    attach: attachCombobox,
    destroyWithin: destroyComboboxesWithin,
    headerOptions: commonHeaderOptions.slice()
  };
  disableBrowserInputHistory(document);
  new MutationObserver(function (mutations) {
    mutations.forEach(function (mutation) {
      Array.prototype.forEach.call(mutation.addedNodes || [], function (node) {
        if (node.nodeType === 1) disableBrowserInputHistory(node);
      });
    });
  }).observe(document.body, {childList: true, subtree: true});
}());
