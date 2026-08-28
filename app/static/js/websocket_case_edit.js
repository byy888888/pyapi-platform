(function () {
  'use strict';
  var options = {projects: [], environments: [], interfaces: [], assertion_comparators: [], assertion_value_types: []};
  var currentCase = null;
  var focusedJsonPath = null;
  var executionEventSource = null;

  function escapeHtml(value) { return $('<div>').text(value == null ? '' : value).html(); }
  function post(url, data) { return $.ajax({url: url, method: 'POST', contentType: 'application/json', data: JSON.stringify(data || {})}); }
  function showError(message) { $('#pageError').removeClass('d-none').text(message); }
  function clearError() { $('#pageError').addClass('d-none').text(''); }
  function selectedInterface() { var id = Number($('#interfaceSelect').val()); return (options.interfaces || []).find(function (item) { return Number(item.id) === id; }); }

  function loadOptions() {
    return post('/api/test-case/options', {}).done(function (resp) {
      options = resp.data || options;
      $('#projectSelect').html((options.projects || []).map(function (item) { return '<option value="' + item.id + '">' + escapeHtml(item.name) + '</option>'; }).join(''));
      $('#environmentSelect').html((options.environments || []).map(function (item) { return '<option value="' + item.id + '">' + escapeHtml(item.name + (item.base_url ? ' - ' + item.base_url : '')) + '</option>'; }).join(''));
      renderInterfaces();
    });
  }

  function renderInterfaces(selectedId) {
    var projectId = Number($('#projectSelect').val());
    var list = (options.interfaces || []).filter(function (item) { return item.interface_type === 'websocket' && Number(item.project_id) === projectId; });
    $('#interfaceSelect').html(list.map(function (item) { return '<option value="' + item.id + '">' + escapeHtml(item.module_name + ' / ' + item.name) + '</option>'; }).join(''));
    if (selectedId) $('#interfaceSelect').val(String(selectedId));
    applyInterface();
  }

  function applyInterface() {
    var item = selectedInterface(); if (!item) { $('#inheritedConfig').text('当前项目下暂无 WebSocket 接口。'); return; }
    if (!currentCase) { $('#requestUrl').val(item.url || ''); $('#caseName').val(item.name || ''); }
    var config = item.ws_config || {}; var summary = [];
    summary.push('握手 Headers：' + Object.keys(config.headers || {}).length + ' 项');
    summary.push('子协议：' + ((config.subprotocols || []).join(', ') || '无'));
    summary.push('连接超时：' + (config.connect_timeout_ms || 5000) + ' ms');
    summary.push('连接后消息：' + ((config.connect_message || {}).enabled ? '自动发送' : '不发送'));
    summary.push('业务心跳：' + ((config.heartbeat || {}).enabled ? ((config.heartbeat || {}).interval_ms + ' ms') : '关闭'));
    $('#inheritedConfig').html('<div class="fw-semibold mb-2">继承接口配置</div>' + summary.map(function (item) { return '<div>' + escapeHtml(item) + '</div>'; }).join(''));
  }

  function loadCase() {
    var id = Number($('#caseId').val());
    if (!id) { applyPrefill(); if (!$('#stepList .ws-step').length) { var iface = selectedInterface() || {}; var message = (iface.ws_config || {}).default_message || {}; addStep('send', {message_type:message.message_type || 'json', content:message.content || ''}); } return $.Deferred().resolve().promise(); }
    return post('/api/test-case/detail', {case_id: id}).done(function (resp) {
      currentCase = resp.data || {}; $('#projectSelect').val(currentCase.project_id); renderInterfaces(currentCase.interface_id); $('#caseName').val(currentCase.name); $('#environmentSelect').val(currentCase.environment_id || $('#environmentSelect').val()); $('#timeoutSeconds').val(currentCase.timeout_seconds || 60); $('#requestUrl').val(currentCase.url || ''); renderSteps(currentCase.ws_steps || []);
    });
  }

  function applyPrefill() { var id = Number($('#prefillInterfaceId').val()); if (!id) return; var item = (options.interfaces || []).find(function (entry) { return Number(entry.id) === id; }); if (!item || item.interface_type !== 'websocket') { showError('预填接口不是有效的 WebSocket 接口'); return; } $('#projectSelect').val(item.project_id); renderInterfaces(item.id); $('#interfaceSelect').val(item.id); applyInterface(); }

  function addStep(type, data) {
    data = data || {}; type = type || data.type || data.action || 'send'; var number = $('#stepList .ws-step').length + 1;
    var label = {send: '发送消息', wait_assert: '等待并校验消息', sleep: '等待时间', close: '主动断开连接'}[type] || type;
    var html = '<div class="ws-step" data-type="' + type + '"><div class="ws-step-header"><div class="d-flex align-items-center gap-2"><span class="ws-flow-number">' + number + '</span><input class="form-control form-control-sm step-name" value="' + escapeHtml(data.name || label) + '"></div><div><button class="btn btn-sm btn-link move-up" type="button">↑</button><button class="btn btn-sm btn-link move-down" type="button">↓</button><button class="btn btn-sm btn-link text-danger remove-step" type="button">删除</button></div></div><div class="ws-step-body">' + stepBody(type, data) + '</div></div>';
    $('#stepList').append(html); var $step = $('#stepList .ws-step').last();
    if (type === 'send') { $step.find('.message-type').val(data.message_type || 'json'); }
    if (type === 'wait_assert') { renderConditions($step, (data.target || {}).conditions || []); renderAssertions($step, data.assertions || []); renderExtractors($step, data.extractors || []); updateTargetMode($step, (data.target || {}).mode || 'next'); $step.find('.failure-action').val(data.failure_action || 'stop'); }
    renumberSteps();
  }

  function stepBody(type, data) {
    if (type === 'send') return '<div class="row g-2"><div class="col-md-3"><select class="form-select message-type"><option value="json">JSON</option><option value="text">文本</option><option value="binary">Binary(Base64)</option></select></div><div class="col-md-9"><textarea class="form-control font-monospace message-content" rows="5" placeholder="支持变量和运行时提取值">' + escapeHtml(data.content || data.message || '') + '</textarea></div></div>';
    if (type === 'sleep') return '<label class="form-label">等待秒数</label><input class="form-control sleep-seconds" type="number" min="0" step="0.1" value="' + escapeHtml(data.seconds || 1) + '">';
    if (type === 'close') return '<div class="text-secondary">执行到这里时主动断开连接；未添加该步骤时，平台会在用例结束后自动关闭。</div>';
    var target = data.target || {};
    return '<div class="row g-2 mb-3"><div class="col-md-3"><label class="form-label">最长等待（秒）</label><input class="form-control wait-timeout" type="number" min="0.1" step="0.1" value="' + escapeHtml(data.timeout_seconds || 10) + '"></div><div class="col-md-5"><label class="form-label">等待哪条消息</label><select class="form-select target-mode"><option value="next">下一条业务消息</option><option value="condition">满足指定条件的消息</option></select></div><div class="col-md-4"><label class="form-label">失败后</label><select class="form-select failure-action"><option value="stop">立即停止用例</option><option value="continue">记录失败并继续</option></select></div></div><div class="target-conditions border rounded p-3 mb-3"><div class="d-flex justify-content-between mb-2"><span class="fw-semibold">目标消息特征（全部满足）</span><button class="btn btn-sm btn-outline-primary add-condition" type="button">添加条件</button></div><div class="condition-list"></div></div><ul class="nav nav-tabs mb-3"><li class="nav-item"><button class="nav-link active" data-bs-toggle="tab" data-bs-target="#assert-' + Date.now() + '-' + Math.random().toString(16).slice(2) + '" type="button">断言</button></li><li class="nav-item"><button class="nav-link" data-bs-toggle="tab" data-bs-target="#extract-' + Date.now() + '-' + Math.random().toString(16).slice(2) + '" type="button">响应提取</button></li></ul><div class="wait-tabs"><div class="assertion-pane"><div class="d-flex justify-content-end mb-2"><button class="btn btn-sm btn-outline-primary add-assertion" type="button">添加断言</button></div><div class="assertion-list"></div></div><div class="extractor-pane d-none"><div class="d-flex justify-content-end mb-2"><button class="btn btn-sm btn-outline-primary add-extractor" type="button">添加提取</button></div><div class="extractor-list"></div></div></div>';
  }

  function comparatorOptions(selected) { selected = selected || 'equals'; return (options.assertion_comparators || []).filter(function (item) { return !['time_less_than','receive_contains_within'].includes(item.value); }).map(function (item) { return '<option value="' + item.value + '"' + (item.value === selected ? ' selected' : '') + '>' + escapeHtml(item.label) + '</option>'; }).join(''); }
  function typeOptions(selected) { selected = selected === 'raw' ? '' : (selected || ''); return (options.assertion_value_types || []).map(function (item) { return '<option value="' + item.value + '"' + (item.value === selected ? ' selected' : '') + '>' + escapeHtml(item.label) + '</option>'; }).join(''); }
  function sourceOptions(selected) { return ['body_json','body_text','body_type','body_length'].map(function (value) { var label = {body_json:'JSONPath',body_text:'消息文本',body_type:'消息类型',body_length:'消息长度'}[value]; return '<option value="' + value + '"' + (value === selected ? ' selected' : '') + '>' + label + '</option>'; }).join(''); }

  function addCondition($step, item) { item = item || {source:'body_json', comparator:'equals', value_type:'string'}; $step.find('.condition-list').append('<div class="ws-condition-row"><select class="form-select condition-source">' + sourceOptions(item.source) + '</select><input class="form-control condition-path ws-jsonpath-input" placeholder="JSONPath" value="' + escapeHtml(item.jsonpath || '') + '"><select class="form-select condition-comparator">' + comparatorOptions(item.comparator) + '</select><select class="form-select condition-type">' + typeOptions(item.value_type || 'string') + '</select><div class="d-flex gap-2"><input class="form-control condition-expected" placeholder="特征值" value="' + escapeHtml(item.expected == null ? '' : item.expected) + '"><button class="btn btn-outline-danger remove-row" type="button">删除</button></div></div>'); }
  function renderConditions($step, items) { (items || []).forEach(function (item) { addCondition($step, item); }); }
  function addAssertion($step, item) { item = item || {source:'body_json', comparator:'equals', value_type:'string'}; $step.find('.assertion-list').append('<div class="ws-assert-row"><input class="form-control assertion-name" placeholder="断言名称" value="' + escapeHtml(item.name || '') + '"><select class="form-select assertion-source">' + sourceOptions(item.source) + '</select><input class="form-control assertion-path ws-jsonpath-input" placeholder="JSONPath" value="' + escapeHtml(item.jsonpath || '') + '"><select class="form-select assertion-comparator">' + comparatorOptions(item.comparator) + '</select><select class="form-select assertion-type">' + typeOptions(item.value_type) + '</select><div class="d-flex gap-2"><input class="form-control assertion-expected" placeholder="期望值" value="' + escapeHtml(item.expected == null ? '' : item.expected) + '"><button class="btn btn-outline-danger remove-row" type="button">删</button></div></div>'); }
  function renderAssertions($step, items) { (items || []).forEach(function (item) { addAssertion($step, item); }); }
  function addExtractor($step, item) { item = item || {}; $step.find('.extractor-list').append('<div class="ws-extractor-row"><input class="form-control extractor-path ws-jsonpath-input" placeholder="JSONPath，如 $.data.token" value="' + escapeHtml(item.jsonpath || '') + '"><input class="form-control extractor-name" placeholder="变量名，如 token" value="' + escapeHtml(item.variable_name || '') + '"><button class="btn btn-outline-danger remove-row" type="button">删除</button></div>'); }
  function renderExtractors($step, items) { (items || []).forEach(function (item) { addExtractor($step, item); }); }

  function updateTargetMode($step, mode) { $step.find('.target-mode').val(mode); $step.find('.target-conditions').toggle(mode === 'condition'); }
  function renumberSteps() { $('#stepList .ws-step').each(function (index) { $(this).find('.ws-flow-number').text(index + 1); }); }
  function renderSteps(items) { $('#stepList').empty(); (items || []).forEach(function (item) { addStep(item.type || item.action, item); }); if (!items || !items.length) addStep('send'); }

  function collectDefinition($row, prefix) { var source = $row.find('.' + prefix + '-source').val(); var result = {name: $row.find('.' + prefix + '-name').val(), source: source, comparator: $row.find('.' + prefix + '-comparator').val(), value_type: $row.find('.' + prefix + '-type').val(), expected: $row.find('.' + prefix + '-expected').val()}; if (source === 'body_json') result.jsonpath = $row.find('.' + prefix + '-path').val(); return result; }
  function collectSteps() {
    var steps = [];
    $('#stepList .ws-step').each(function () { var $step = $(this); var type = $step.data('type'); var step = {type:type, name:$step.find('.step-name').val(), failure_action:$step.find('.failure-action').val() || 'stop'};
      if (type === 'send') { step.message_type = $step.find('.message-type').val(); step.content = $step.find('.message-content').val(); }
      if (type === 'sleep') step.seconds = Number($step.find('.sleep-seconds').val() || 0);
      if (type === 'wait_assert') { step.timeout_seconds = Number($step.find('.wait-timeout').val() || 10); step.target = {mode:$step.find('.target-mode').val(), consume:true, conditions:[]}; $step.find('.ws-condition-row').each(function () { var source = $(this).find('.condition-source').val(); step.target.conditions.push({name:'目标消息特征', source:source, jsonpath:source === 'body_json' ? $(this).find('.condition-path').val() : undefined, comparator:$(this).find('.condition-comparator').val(), value_type:$(this).find('.condition-type').val(), expected:$(this).find('.condition-expected').val()}); }); step.assertions = []; $step.find('.ws-assert-row').each(function () { step.assertions.push(collectDefinition($(this), 'assertion')); }); step.extractors = []; $step.find('.ws-extractor-row').each(function () { step.extractors.push({jsonpath:$(this).find('.extractor-path').val(), variable_name:$(this).find('.extractor-name').val(), required:true}); }); }
      steps.push(step);
    }); return steps;
  }

  function collectPayload() { var item = selectedInterface(); return {project_id:Number($('#projectSelect').val()), interface_id:Number($('#interfaceSelect').val()), environment_id:Number($('#environmentSelect').val()) || null, name:$.trim($('#caseName').val()) || (item && item.name), url:$.trim($('#requestUrl').val()), timeout_seconds:Number($('#timeoutSeconds').val() || 60), ws_steps:collectSteps(), ws_config_override:{}, is_active:true}; }
  function save() { clearError(); var payload = collectPayload(); if (!payload.interface_id) { showError('请选择 WebSocket 接口'); return $.Deferred().reject().promise(); } if (!payload.environment_id) { showError('请选择执行环境'); return $.Deferred().reject().promise(); } var id = Number($('#caseId').val()); if (id) payload.case_id = id; return post(id ? '/api/test-case/save' : '/api/test-case/create', payload).done(function (resp) { $('#caseId').val(resp.data.id); currentCase = resp.data; AppToast.success('WebSocket 用例保存成功'); }).fail(function (xhr) { showError((xhr.responseJSON && xhr.responseJSON.message) || '保存失败'); }); }
  function run() {
    save().done(function (resp) {
      stopExecutionStream(); clearError(); $('#runButton').prop('disabled', true).text('执行中...'); $('#runStatus').removeClass().addClass('badge text-bg-secondary').text('执行中'); $('#messageLog').html('<span class="text-secondary">等待实时消息...</span>'); $('#stepResults').html('执行中...'); $('#jsonpathList').empty();
      post('/api/test-case/debug/start', {case_id:Number(resp.data.id), environment_id:Number($('#environmentSelect').val())}).done(function (startResp) {
        startExecutionStream(startResp.data.execution_id);
      }).fail(function (xhr) {
        showError((xhr.responseJSON && xhr.responseJSON.message) || '执行启动失败'); finishExecutionUi();
      });
    });
  }

  function startExecutionStream(executionId) {
    if (!window.EventSource) { showError('当前浏览器不支持 SSE 实时消息，请更换现代浏览器'); finishExecutionUi(); return; }
    executionEventSource = new EventSource('/api/test-case/debug/events?execution_id=' + encodeURIComponent(executionId));
    executionEventSource.addEventListener('websocket_message', function (event) {
      var item;
      try { item = JSON.parse(event.data); } catch (error) { showError('实时消息解析失败：' + error.message); return; }
      appendLiveMessage(item);
    });
    executionEventSource.addEventListener('case_result', function (event) {
      var result;
      try { result = JSON.parse(event.data); } catch (error) { showError('执行结果解析失败：' + error.message); finishExecutionUi(); return; }
      renderResult(result); finishExecutionUi();
    });
    executionEventSource.addEventListener('case_error', function (event) {
      var error = {};
      try { error = JSON.parse(event.data); } catch (_parseError) { error.message = event.data; }
      $('#runStatus').removeClass().addClass('badge text-bg-danger').text('失败'); showError(error.message || 'WebSocket 用例执行失败'); finishExecutionUi();
    });
    executionEventSource.onerror = function () {
      if (executionEventSource && executionEventSource.readyState === EventSource.CLOSED) { showError('执行结果实时连接已断开'); finishExecutionUi(); }
    };
  }

  function appendLiveMessage(item) {
    if ($('#messageLog .text-secondary').length) $('#messageLog').empty();
    var direction = item.direction === 'send' ? '发送' : (item.direction === 'receive' ? '接收' : '系统');
    var data = typeof item.data === 'string' ? item.data : JSON.stringify(item.data);
    $('#messageLog').append('<div><span class="text-warning">[' + direction + ']</span> ' + escapeHtml(data) + '</div>');
    $('#messageLog').scrollTop($('#messageLog')[0].scrollHeight);
  }

  function stopExecutionStream() { if (executionEventSource) executionEventSource.close(); executionEventSource = null; }
  function finishExecutionUi() { stopExecutionStream(); $('#runButton').prop('disabled', false).text('▶ 运行用例'); }

  function renderResult(result) { var runner = result.runner || {}; $('#runStatus').removeClass().addClass('badge ' + (result.success ? 'text-bg-success' : 'text-bg-danger')).text(result.success ? '通过' : '失败'); $('#stepResults').html((runner.steps || []).map(function (step, index) { return '<div class="border rounded p-2 mb-2"><div class="d-flex justify-content-between"><span class="fw-semibold">' + (index + 1) + '. ' + escapeHtml(step.name || step.type) + '</span><span class="badge ' + (step.passed ? 'text-bg-success' : 'text-bg-danger') + '">' + (step.passed ? '通过' : '失败') + '</span></div><div class="small text-secondary mt-1">' + escapeHtml(step.message || '') + ' · ' + escapeHtml(step.response_time_ms == null ? step.time_taken_ms : step.response_time_ms) + ' ms</div>' + assertionResultHtml(step.assertions || []) + '</div>'; }).join('') || '暂无步骤结果'); $('#messageLog').html((runner.ws_messages || []).map(function (item) { var direction = item.direction === 'send' ? '发送' : (item.direction === 'receive' ? '接收' : '系统'); var data = typeof item.data === 'string' ? item.data : JSON.stringify(item.data); return '<div><span class="text-warning">[' + direction + ']</span> ' + escapeHtml(data) + '</div>'; }).join('') || '暂无消息'); $('#jsonpathList').html((result.jsonpaths || []).map(function (path) { return '<button class="btn btn-sm btn-outline-secondary jsonpath-choice" type="button">' + escapeHtml(path) + '</button>'; }).join('') || '<span class="text-secondary small">未匹配到可解析的 JSON 消息</span>'); }
  function assertionResultHtml(items) { if (!items.length) return ''; return '<div class="table-responsive mt-2"><table class="table table-sm mb-0"><thead><tr><th>断言</th><th>期望</th><th>实际</th><th>结果</th></tr></thead><tbody>' + items.map(function (item) { return '<tr><td>' + escapeHtml(item.name) + '</td><td>' + escapeHtml(item.expected) + ' (' + escapeHtml(item.expected_type || item.value_type) + ')</td><td>' + escapeHtml(typeof item.actual === 'object' ? JSON.stringify(item.actual) : item.actual) + ' (' + escapeHtml(item.actual_type) + ')</td><td><span class="badge ' + (item.passed ? 'text-bg-success' : 'text-bg-danger') + '">' + (item.passed ? '通过' : '失败') + '</span></td></tr>'; }).join('') + '</tbody></table></div>'; }

  $('#projectSelect').on('change', function () { currentCase = null; renderInterfaces(); }); $('#interfaceSelect').on('change', function () { currentCase = null; applyInterface(); }); $('.add-step').on('click', function () { addStep($(this).data('type')); }); $('#saveButton').on('click', save); $('#runButton').on('click', run);
  $('#stepList').on('click', '.remove-step', function () { $(this).closest('.ws-step').remove(); renumberSteps(); }).on('click', '.move-up', function () { var $step = $(this).closest('.ws-step'); $step.prev().before($step); renumberSteps(); }).on('click', '.move-down', function () { var $step = $(this).closest('.ws-step'); $step.next().after($step); renumberSteps(); }).on('click', '.add-condition', function () { addCondition($(this).closest('.ws-step')); }).on('click', '.add-assertion', function () { addAssertion($(this).closest('.ws-step')); }).on('click', '.add-extractor', function () { addExtractor($(this).closest('.ws-step')); }).on('click', '.remove-row', function () { $(this).closest('.ws-condition-row, .ws-assert-row, .ws-extractor-row').remove(); }).on('change', '.target-mode', function () { updateTargetMode($(this).closest('.ws-step'), $(this).val()); }).on('click', '.nav-link', function () { var $tabs = $(this).closest('.ws-step'); var extractor = $(this).text().indexOf('提取') >= 0; $tabs.find('.assertion-pane').toggle(!extractor); $tabs.find('.extractor-pane').toggle(extractor); }).on('focusin', '.ws-jsonpath-input', function () { focusedJsonPath = this; });
  $('#jsonpathList').on('click', '.jsonpath-choice', function () { var value = $(this).text(); if (focusedJsonPath && document.body.contains(focusedJsonPath) && $(focusedJsonPath).is(':visible')) { $(focusedJsonPath).val(value).trigger('input'); return; } var $activeStep = $('#stepList .ws-step:has(.nav-link.active)').last(); var $target = $activeStep.find('.ws-jsonpath-input:visible').last(); if ($target.length) $target.val(value).trigger('input'); });
  window.addEventListener('beforeunload', stopExecutionStream);
  loadOptions().done(loadCase).fail(function (xhr) { showError((xhr.responseJSON && xhr.responseJSON.message) || '页面数据加载失败'); });
}());
