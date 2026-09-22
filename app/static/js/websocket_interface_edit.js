(function () {
  'use strict';
  var options = {projects: [], modules: [], environments: []};
  var sessionId = '';
  var lastSequence = 0;
  var pendingMessages = {};
  var eventSource = null;
  var moduleCombobox = AppCombobox.attach(document.getElementById('moduleInput'), {
    options: [],
    allowCustom: true,
    emptyText: '当前项目暂无模块，可直接输入新模块名称',
    customText: '创建新模块：'
  });

  function escapeHtml(value) { return $('<div>').text(value == null ? '' : value).html(); }
  function post(url, data) { return $.ajax({url: url, method: 'POST', contentType: 'application/json', data: JSON.stringify(data || {})}); }
  function showError(message) { $('#pageError').removeClass('d-none').text(message); }
  function clearError() { $('#pageError').addClass('d-none').text(''); }

  function loadOptions() {
    return post('/api/interface-definition/options', {}).done(function (resp) {
      options = resp.data || options;
      AppSelect.fill('#projectSelect', options.projects, {
        label: function (item) { return item.name; },
        emptyText: '暂无项目',
        emptyHint: '暂无项目，请先到「项目管理」创建'
      });
      AppSelect.fill('#environmentSelect', options.environments, {
        label: function (item) { return item.name + (item.base_url ? ' - ' + item.base_url : ''); },
        emptyText: '暂无环境',
        emptyHint: '暂无执行环境，请先到「环境与变量管理」创建'
      });
      renderModules('');
    });
  }

  function renderModules(selected) {
    var projectId = Number($('#projectSelect').val());
    moduleCombobox.setOptions((options.modules || []).filter(function (item) { return Number(item.project_id) === projectId; }).map(function (item) { return {value:item.name, label:item.name}; }));
    if (selected !== undefined) $('#moduleInput').val(selected || '');
  }

  function selectedModule() {
    var name = $.trim($('#moduleInput').val()).toLowerCase();
    var projectId = Number($('#projectSelect').val());
    return (options.modules || []).find(function (item) { return Number(item.project_id) === projectId && item.name.toLowerCase() === name; });
  }

  function addHeader(row) {
    row = row || {};
    $('#headerRows').append('<div class="ws-kv-row"><input class="form-control ws-header-key" placeholder="Header Key" value="' + escapeHtml(row.key || '') + '"><input class="form-control ws-header-value" placeholder="Header Value，支持 {{变量}}" value="' + escapeHtml(row.value || '') + '"><button class="btn btn-outline-danger remove-header" type="button">删除</button></div>');
  }

  function headersObject() {
    var result = {};
    $('#headerRows .ws-kv-row').each(function () { var key = $.trim($(this).find('.ws-header-key').val()); if (key) result[key] = $(this).find('.ws-header-value').val(); });
    return result;
  }

  function renderHeaders(headers) {
    $('#headerRows').empty();
    Object.keys(headers || {}).forEach(function (key) { addHeader({key: key, value: headers[key]}); });
  }

  function messageConfig(prefix) {
    return {enabled: $('#' + prefix + 'Enabled').is(':checked'), message_type: $('#' + prefix + 'Type').val(), content: $('#' + prefix + 'Content').val()};
  }

  function collectConfig() {
    return {
      headers: headersObject(),
      subprotocols: ($('#subprotocols').val() || '').split(',').map(function (item) { return $.trim(item); }).filter(Boolean),
      connect_timeout_ms: Number($('#connectTimeout').val() || 5000),
      connect_message: messageConfig('connectMessage'),
      heartbeat: $.extend(messageConfig('heartbeat'), {interval_ms: Number($('#heartbeatInterval').val() || 30000)}),
      default_message: {message_type: $('#messageType').val(), content: $('#messageContent').val()}
    };
  }

  function collectPayload() {
    var module = selectedModule();
    return {project_id: Number($('#projectSelect').val()), module_id: module ? module.id : null, module_name: $.trim($('#moduleInput').val()), name: $.trim($('#interfaceName').val()), interface_type: 'websocket', url: $.trim($('#requestUrl').val()), ws_config: collectConfig(), is_active: $('#interfaceActive').is(':checked')};
  }

  function validate(payload) {
    if (!payload.project_id) return '请选择项目';
    if (!payload.module_name) return '请选择或输入所属模块';
    if (!payload.name) return '接口名称不能为空';
    if (!payload.url) return 'WebSocket 连接地址不能为空';
    if (payload.ws_config.connect_message.enabled && !payload.ws_config.connect_message.content) return '已开启连接后消息，请填写内容';
    if (payload.ws_config.heartbeat.enabled && !payload.ws_config.heartbeat.content) return '已开启业务心跳，请填写内容';
    return '';
  }

  function save() {
    clearError();
    var payload = collectPayload();
    var error = validate(payload); if (error) { showError(error); return $.Deferred().reject().promise(); }
    var id = Number($('#interfaceId').val()); if (id) payload.interface_id = id;
    return post(id ? '/api/interface-definition/save' : '/api/interface-definition/create', payload).done(function (resp) { $('#interfaceId').val(resp.data.id); AppToast.success('WebSocket 接口保存成功'); }).fail(function (xhr) { showError((xhr.responseJSON && xhr.responseJSON.message) || '保存失败'); });
  }

  function loadDetail() {
    var id = Number($('#interfaceId').val()); if (!id) return $.Deferred().resolve().promise();
    return post('/api/interface-definition/detail', {interface_id: id}).done(function (resp) {
      var item = resp.data || {}; var config = item.ws_config || {};
      $('#projectSelect').val(item.project_id); renderModules(item.module_name); $('#interfaceName').val(item.name); $('#requestUrl').val(item.url); $('#interfaceActive').prop('checked', item.is_active !== false);
      renderHeaders(config.headers || {}); $('#subprotocols').val((config.subprotocols || []).join(',')); $('#connectTimeout').val(config.connect_timeout_ms || 5000);
      fillMessage('connectMessage', config.connect_message || {}); fillMessage('heartbeat', config.heartbeat || {}); $('#heartbeatInterval').val((config.heartbeat || {}).interval_ms || 30000);
      $('#messageType').val((config.default_message || {}).message_type || 'json'); $('#messageContent').val((config.default_message || {}).content || ''); toggleOptionalFields();
    });
  }

  function fillMessage(prefix, config) { $('#' + prefix + 'Enabled').prop('checked', Boolean(config.enabled)); $('#' + prefix + 'Type').val(config.message_type || 'text'); $('#' + prefix + 'Content').val(config.content || ''); }
  function toggleOptionalFields() { $('.connect-message-fields').toggle($('#connectMessageEnabled').is(':checked')); $('.heartbeat-fields').toggle($('#heartbeatEnabled').is(':checked')); }

  function connect() {
    if (sessionId) { disconnect(); return; }
    clearError(); var payload = collectPayload(); var error = validate(payload); if (error) { showError(error); return; }
    $('#connectButton').prop('disabled', true).text('连接中...');
    post('/api/websocket-debug/connect', {project_id: payload.project_id, environment_id: Number($('#environmentSelect').val()), url: payload.url, ws_config: payload.ws_config}).done(function (resp) {
      stopEventStream(); lastSequence = 0; pendingMessages = {}; $('#messageLog').empty(); sessionId = resp.data.session_id; $('#connectButton').prop('disabled', false).removeClass('btn-primary').addClass('btn-outline-danger').text('断开连接'); $('#sendButton').prop('disabled', false); $('#connectionStatus').removeClass().addClass('badge text-bg-success').text('已连接'); renderMessages(resp.data.messages || []); startEventStream();
    }).fail(function (xhr) { $('#connectButton').prop('disabled', false).text('建立连接'); showError((xhr.responseJSON && xhr.responseJSON.message) || '连接失败'); });
  }

  function disconnect() {
    var id = sessionId; sessionId = ''; stopEventStream(); lastSequence = 0; pendingMessages = {}; resetConnectionUi(); if (id) post('/api/websocket-debug/disconnect', {session_id: id});
  }

  function resetConnectionUi() { $('#connectButton').prop('disabled', false).removeClass('btn-outline-danger').addClass('btn-primary').text('建立连接'); $('#sendButton').prop('disabled', true); $('#connectionStatus').removeClass().addClass('badge text-bg-secondary').text('未连接'); }
  function startEventStream() {
    stopEventStream();
    if (!sessionId || !window.EventSource) { showError('当前浏览器不支持 SSE 实时消息，请更换现代浏览器'); return; }
    var streamSession = sessionId;
    eventSource = new EventSource('/api/websocket-debug/events?session_id=' + encodeURIComponent(streamSession) + '&after_sequence=' + lastSequence);
    eventSource.addEventListener('websocket_message', function (event) {
      if (streamSession !== sessionId) return;
      var item;
      try { item = JSON.parse(event.data); } catch (error) { showError('实时消息解析失败：' + error.message); return; }
      renderMessages([item]);
      if (item.event === 'closed') { var reason = item.data || 'WebSocket 连接已关闭'; sessionId = ''; stopEventStream(); resetConnectionUi(); showError(reason); }
    });
    eventSource.onopen = function () { if (streamSession === sessionId) clearError(); };
    eventSource.onerror = function () { if (streamSession === sessionId && eventSource && eventSource.readyState === EventSource.CLOSED) showError('实时消息连接已断开，请重新建立 WebSocket 连接'); };
  }
  function stopEventStream() { if (eventSource) eventSource.close(); eventSource = null; }

  function renderMessages(messages) {
    (messages || []).forEach(function (item) {
      var sequence = Number(item.sequence || 0);
      if (sequence > lastSequence) pendingMessages[sequence] = item;
    });
    messages = [];
    while (pendingMessages[lastSequence + 1]) {
      lastSequence += 1;
      messages.push(pendingMessages[lastSequence]);
      delete pendingMessages[lastSequence];
    }
    if (!messages.length) return;
    if ($('#messageLog .text-secondary').length) $('#messageLog').empty();
    messages.forEach(function (item) { var time = new Date(Number(item.timestamp || 0) * 1000).toLocaleTimeString(); var direction = item.direction === 'send' ? '发送' : (item.direction === 'receive' ? '接收' : '系统'); var data = typeof item.data === 'string' ? item.data : JSON.stringify(item.data, null, 2); $('#messageLog').append('<div class="ws-log-row ws-log-' + item.direction + '"><span>' + escapeHtml(time) + '</span><span>' + direction + (item.is_heartbeat ? '·心跳' : '') + '</span><span class="text-break">' + escapeHtml(data) + '</span></div>'); });
    $('#messageLog').scrollTop($('#messageLog')[0].scrollHeight);
  }

  function sendMessage() { if (!sessionId) return; post('/api/websocket-debug/send', {session_id: sessionId, message_type: $('#messageType').val(), content: $('#messageContent').val()}).fail(function (xhr) { showError((xhr.responseJSON && xhr.responseJSON.message) || '发送失败'); }); }
  function formatMessage() { if ($('#messageType').val() !== 'json') return; try { $('#messageContent').val(JSON.stringify(JSON.parse($('#messageContent').val()), null, 2)); } catch (error) { showError('JSON 格式错误：' + error.message); } }

  $('#projectSelect').on('change', function () { renderModules(''); }); $('#addHeaderButton').on('click', function () { addHeader(); }); $('#headerRows').on('click', '.remove-header', function () { $(this).closest('.ws-kv-row').remove(); });
  $('#connectMessageEnabled, #heartbeatEnabled').on('change', toggleOptionalFields); $('#saveButton').on('click', save); $('#connectButton').on('click', connect); $('#sendButton').on('click', sendMessage); $('#formatMessageButton').on('click', formatMessage);
  window.addEventListener('beforeunload', function () { stopEventStream(); if (sessionId && navigator.sendBeacon) navigator.sendBeacon('/api/websocket-debug/disconnect', new Blob([JSON.stringify({session_id: sessionId})], {type: 'application/json'})); });
  toggleOptionalFields(); loadOptions().done(loadDetail).fail(function (xhr) { showError((xhr.responseJSON && xhr.responseJSON.message) || '页面数据加载失败'); });
}());
