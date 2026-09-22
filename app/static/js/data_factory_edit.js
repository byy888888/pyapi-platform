(function () {
  'use strict';

  var factoryId = window.dataFactoryPage.factoryId;
  var optionData = {};
  var interfaceGroups = [];
  var interfaceMap = {};
  var steps = [];
  var selectedIndex = -1;
  var previousProjectId = '';
  var debugResultCache = {};
  var focusedJsonpathByStep = {};
  var stepSeed = 0;

  function escapeHtml(value) {
    return $('<div>').text(value == null ? '' : String(value)).html();
  }

  function prettyJson(value) {
    return JSON.stringify(value == null ? {} : value, null, 2);
  }

  function newRequestStep() {
    stepSeed += 1;
    return {
      _key: stepSeed,
      step_type: 'request',
      source_type: 'custom',
      interface_id: null,
      name: '新接口步骤',
      method: 'POST',
      url: '',
      body_type: 'json',
      params: {},
      headers: {},
      body: {},
      timeout_seconds: 30,
      extractors: [],
      assertions: [],
      _tab: 'params'
    };
  }

  function newWaitStep() {
    stepSeed += 1;
    return {
      _key: stepSeed,
      step_type: 'wait',
      name: '等待 2 秒',
      wait_seconds: 2
    };
  }

  function normalizeStep(item) {
    var step = $.extend(true, {}, item || {});
    stepSeed += 1;
    step._key = stepSeed;
    step.step_type = step.step_type || 'request';
    if (step.step_type === 'wait') {
      step.name = step.name || '等待';
      step.wait_seconds = Number(step.wait_seconds || 1);
      return step;
    }
    step.source_type = step.source_type || 'custom';
    step.method = step.method || 'POST';
    step.body_type = step.body_type || 'none';
    step.params = step.params || {};
    step.headers = step.headers || {};
    step.body = step.body == null ? {} : step.body;
    step.timeout_seconds = Number(step.timeout_seconds || 30);
    step.extractors = step.extractors || [];
    step.assertions = step.assertions || [];
    step._tab = 'params';
    return step;
  }

  function renderFlow() {
    var html = steps.map(function (step, index) {
      var isWait = step.step_type === 'wait';
      var meta = isWait
        ? '等待 ' + Number(step.wait_seconds || 0) + ' 秒'
        : (step.method || 'GET') + ' ' + (step.url || '尚未填写 URL');
      var node = '<div class="flow-node ' + (isWait ? 'wait ' : '') + (index === selectedIndex ? 'active' : '') + '" data-index="' + index + '">' +
        '<div class="flow-node-main"><div class="flow-index">' + (index + 1) + '</div><div class="flow-summary"><div class="name">' + escapeHtml(step.name || '未命名步骤') + '</div><div class="meta">' + escapeHtml(meta) + '</div></div></div>' +
        '<div class="flow-actions"><button class="btn btn-sm btn-link text-secondary move-step-up" title="上移">↑</button><button class="btn btn-sm btn-link text-secondary move-step-down" title="下移">↓</button><button class="btn btn-sm btn-link text-danger delete-step" title="删除">删除</button></div>' +
      '</div>';
      return node + (index < steps.length - 1 ? '<div class="flow-arrow">↓</div>' : '');
    }).join('');
    html += '<div class="flow-add"><button id="addRequestStep" class="btn btn-sm btn-outline-primary">＋接口步骤</button><button id="addWaitStep" class="btn btn-sm btn-outline-secondary">＋等待步骤</button></div>';
    $('#flowCanvas').html(html);
    $('#stepCount').text(steps.length + ' 个步骤');
  }

  function sourceOptions(selected) {
    return [
      {value: 'custom', label: '自定义 URL'},
      {value: 'interface', label: '引用接口库'}
    ].map(function (item) {
      return '<option value="' + item.value + '"' + (selected === item.value ? ' selected' : '') + '>' + item.label + '</option>';
    }).join('');
  }

  function interfaceOptions(selectedId) {
    var html = '<option value="">请选择接口</option>';
    interfaceGroups.forEach(function (group) {
      html += '<optgroup label="' + escapeHtml(group.module_name) + '">';
      (group.interfaces || []).forEach(function (item) {
        html += '<option value="' + item.id + '"' + (Number(selectedId) === item.id ? ' selected' : '') + '>' + escapeHtml(item.method + ' · ' + item.name + ' · ' + item.url) + '</option>';
      });
      html += '</optgroup>';
    });
    return html;
  }

  function methodOptions(selected) {
    return (optionData.methods || ['GET', 'POST']).map(function (method) {
      return '<option value="' + method + '"' + (selected === method ? ' selected' : '') + '>' + method + '</option>';
    }).join('');
  }

  function objectRows(value) {
    var rows = Object.keys(value || {}).map(function (key) {
      var itemValue = value[key];
      return {key: key, value: typeof itemValue === 'string' ? itemValue : JSON.stringify(itemValue)};
    });
    return rows.length ? rows : [{key: '', value: ''}];
  }

  function kvRows(kind, value) {
    return objectRows(value).map(function (row) {
      return '<div class="factory-kv-row" data-kind="' + kind + '"><input class="form-control form-control-sm kv-key" placeholder="Key" value="' + escapeHtml(row.key) + '"><input class="form-control form-control-sm kv-value" placeholder="Value，支持内置函数和 ${变量名}" value="' + escapeHtml(row.value) + '"><button class="btn btn-sm btn-outline-danger remove-kv" type="button">删除</button></div>';
    }).join('');
  }

  function extractorRows(items) {
    if (!items.length) return '<div class="text-secondary small extractor-empty">暂无提取器</div>';
    return items.map(function (item) {
      return '<div class="extractor-row"><input class="form-control form-control-sm extractor-name" placeholder="变量名称" value="' + escapeHtml(item.variable_name || '') + '"><input class="form-control form-control-sm extractor-jsonpath" placeholder="JSONPath，例如 $.data.id" value="' + escapeHtml(item.jsonpath || '') + '"><label class="text-nowrap small"><input class="form-check-input extractor-required" type="checkbox"' + (item.required ? ' checked' : '') + '> 必填</label><button class="btn btn-sm btn-outline-danger remove-extractor" type="button">删除</button></div>';
    }).join('');
  }

  function assertionSourceOptions(selected) {
    var values = [
      ['status_code', '状态码 status_code'], ['headers', '响应头 headers'],
      ['body_json', 'JSON 响应 body_json'], ['body_text', '响应文本 body_text'],
      ['body_type', '响应类型 body_type'], ['body_length', '响应大小 body_length'],
      ['elapsed_ms', '耗时 elapsed_ms']
    ];
    return values.map(function (item) {
      return '<option value="' + item[0] + '"' + (selected === item[0] ? ' selected' : '') + '>' + item[1] + '</option>';
    }).join('');
  }

  function comparatorOptions(selected) {
    selected = selected || 'equals';
    return (optionData.assertion_comparators || []).map(function (item) {
      return '<option value="' + item.value + '"' + (selected === item.value ? ' selected' : '') + '>' + escapeHtml(item.label) + '</option>';
    }).join('');
  }

  function valueTypeOptions(selected) {
    selected = selected === 'raw' ? '' : (selected || '');
    return (optionData.assertion_value_types || []).map(function (item) {
      return '<option value="' + item.value + '"' + (selected === item.value ? ' selected' : '') + '>' + escapeHtml(item.label) + '</option>';
    }).join('');
  }

  function assertionRows(items) {
    if (!items.length) return '<div class="text-secondary small assertion-empty">暂无断言；接口仍会默认校验 HTTP 状态码为 2xx。</div>';
    return items.map(function (item) {
      var source = item.source || 'body_json';
      var comparator = item.comparator || 'equals';
      var noExpected = comparator === 'is_none' || comparator === 'is_not_none';
      var pathField = source === 'body_json'
        ? '<input class="form-control form-control-sm assertion-jsonpath" placeholder="JSONPath" value="' + escapeHtml(item.jsonpath || '') + '">'
        : (source === 'headers' ? '<input class="form-control form-control-sm assertion-header" placeholder="响应头名称" value="' + escapeHtml(item.header || '') + '">' : '<input class="form-control form-control-sm" disabled value="无需定位字段">');
      return '<div class="assertion-row"><input class="form-control form-control-sm assertion-name" placeholder="断言名称" value="' + escapeHtml(item.name || '') + '"><select class="form-select form-select-sm assertion-source">' + assertionSourceOptions(source) + '</select><span class="assertion-locator">' + pathField + '</span><select class="form-select form-select-sm assertion-comparator">' + comparatorOptions(comparator) + '</select><select class="form-select form-select-sm assertion-value-type"' + (noExpected ? ' disabled' : '') + '>' + valueTypeOptions(item.value_type) + '</select><button class="btn btn-sm btn-outline-danger remove-assertion" type="button">删除</button><input class="form-control form-control-sm assertion-expected" placeholder="' + (noExpected ? '该比较器不需要期望值' : '期望值') + '" value="' + escapeHtml(item.expected == null ? '' : item.expected) + '"' + (noExpected ? ' disabled' : '') + '></div>';
    }).join('');
  }

  function bodyPanel(step) {
    var type = step.body_type || 'none';
    var buttons = (optionData.body_types || ['none', 'form-data', 'x-www-form-urlencoded', 'json', 'raw']).filter(function (item) { return item !== 'form'; }).map(function (item) {
      var label = item === 'json' ? 'JSON' : item;
      return '<button type="button" class="btn btn-sm btn-outline-secondary body-type' + (type === item ? ' active' : '') + '" data-value="' + item + '">' + label + '</button>';
    }).join(' ');
    var content = '<div class="d-flex flex-wrap gap-2 mb-3">' + buttons + '</div>';
    if (type === 'none') return content + '<div class="text-secondary py-4">当前请求不发送 Body。</div>';
    if (type === 'form-data' || type === 'x-www-form-urlencoded' || type === 'form') {
      return content + '<div id="bodyRows">' + kvRows('body', step.body || {}) + '</div><button class="btn btn-sm btn-outline-primary add-kv" data-kind="body" type="button">添加参数</button>';
    }
    var text = type === 'json' ? prettyJson(step.body) : String(step.body == null ? '' : step.body);
    return content + '<textarea id="bodyText" class="form-control font-monospace" rows="12" placeholder="请求正文">' + escapeHtml(text) + '</textarea>' + (type === 'json' ? '<button id="beautifyBody" type="button" class="btn btn-sm btn-outline-secondary mt-2">格式化 JSON</button>' : '');
  }

  function requestTabs(step) {
    var active = step._tab || 'params';
    var definitions = [
      ['params', 'Params'], ['body', 'Body'], ['headers', 'Headers'],
      ['extractors', '响应提取'], ['assertions', '断言']
    ];
    var tabs = definitions.map(function (item) {
      var count = item[0] === 'extractors' ? step.extractors.length : (item[0] === 'assertions' ? step.assertions.length : null);
      return '<button class="nav-link factory-tab' + (active === item[0] ? ' active' : '') + '" data-tab="' + item[0] + '" type="button">' + item[1] + (count == null ? '' : ' <span class="badge text-bg-light">' + count + '</span>') + '</button>';
    }).join('');
    return '<div class="nav factory-tabs">' + tabs + '</div>' +
      '<div class="factory-tab-pane' + (active === 'params' ? ' active' : '') + '" data-pane="params"><div id="paramsRows">' + kvRows('params', step.params) + '</div><button class="btn btn-sm btn-outline-primary add-kv" data-kind="params" type="button">添加参数</button></div>' +
      '<div class="factory-tab-pane' + (active === 'body' ? ' active' : '') + '" data-pane="body">' + bodyPanel(step) + '</div>' +
      '<div class="factory-tab-pane' + (active === 'headers' ? ' active' : '') + '" data-pane="headers"><div id="headersRows">' + kvRows('headers', step.headers) + '</div><button class="btn btn-sm btn-outline-primary add-kv" data-kind="headers" type="button">添加 Header</button></div>' +
      '<div class="factory-tab-pane' + (active === 'extractors' ? ' active' : '') + '" data-pane="extractors"><div class="d-flex justify-content-between mb-2"><div class="small text-secondary">后续步骤通过 ${变量名} 使用提取值。</div><button id="addExtractor" class="btn btn-sm btn-outline-primary" type="button">添加提取器</button></div><div id="extractorRows">' + extractorRows(step.extractors) + '</div></div>' +
      '<div class="factory-tab-pane' + (active === 'assertions' ? ' active' : '') + '" data-pane="assertions"><div class="d-flex justify-content-between mb-2"><div class="small text-secondary">断言使用后端强类型比较，选定字符串与整数不会互相判等。</div><button id="addAssertion" class="btn btn-sm btn-outline-primary" type="button">添加断言</button></div><div id="assertionRows">' + assertionRows(step.assertions) + '</div></div>';
  }

  function renderStepConfig() {
    if (selectedIndex < 0 || !steps[selectedIndex]) {
      $('#stepConfig').html('<div class="config-empty">请在中间选择或添加步骤</div>');
      return;
    }
    var step = steps[selectedIndex];
    if (step.step_type === 'wait') {
      $('#stepConfig').html('<div class="mb-3"><label class="form-label">步骤名称</label><input id="stepName" class="form-control" maxlength="128" value="' + escapeHtml(step.name) + '"></div><div><label class="form-label">等待时长（秒）</label><input id="waitSeconds" class="form-control" type="number" min="0.1" max="3600" step="0.1" value="' + escapeHtml(step.wait_seconds) + '"><div class="form-text">当前轮执行到此步骤时暂停，完成后继续下一个步骤。</div></div>');
      return;
    }
    var interfaceVisible = step.source_type === 'interface';
    var html = '<div class="row g-2"><div class="col-md-4"><label class="form-label">接口来源</label><select id="stepSource" class="form-select">' + sourceOptions(step.source_type) + '</select></div><div class="col-md-8" id="interfacePicker"' + (interfaceVisible ? '' : ' style="display:none"') + '><label class="form-label">按模块选择接口</label><select id="stepInterface" class="form-select">' + interfaceOptions(step.interface_id) + '</select></div><div class="col-md-8"><label class="form-label">步骤名称</label><input id="stepName" class="form-control" maxlength="128" value="' + escapeHtml(step.name || '') + '"></div><div class="col-md-4"><label class="form-label">超时时间（秒）</label><input id="stepTimeout" class="form-control" type="number" min="1" max="120" value="' + step.timeout_seconds + '"></div></div>' +
      '<div class="request-line mt-3"><select id="stepMethod" class="form-select fw-semibold">' + methodOptions(step.method) + '</select><input id="stepUrl" class="form-control font-monospace" placeholder="/api/create 或 http://..." value="' + escapeHtml(step.url || '') + '"><button id="debugStep" class="btn btn-primary" type="button">发送</button></div>' +
      '<div class="form-text mt-2">请求参数可使用 ${uuid()}、${timestamp()}、${random_int(1,100)}、${random_string(12)}、${random_mobile()} 和前置步骤的 ${变量名}。</div>' + requestTabs(step) + '<div id="debugResult" class="debug-result" style="display:none;"></div>';
    $('#stepConfig').html(html);
    renderCachedDebugResult(step);
  }

  function renderAll() {
    renderFlow();
    renderStepConfig();
  }

  function rowsToObject(selector) {
    var result = {};
    $(selector).find('.factory-kv-row').each(function () {
      var key = $(this).find('.kv-key').val().trim();
      if (key) result[key] = $(this).find('.kv-value').val();
    });
    return result;
  }

  function collectExtractors() {
    var result = [];
    $('#extractorRows .extractor-row').each(function () {
      var item = {
        variable_name: $(this).find('.extractor-name').val().trim(),
        jsonpath: $(this).find('.extractor-jsonpath').val().trim(),
        required: $(this).find('.extractor-required').is(':checked')
      };
      if (item.variable_name || item.jsonpath) result.push(item);
    });
    return result;
  }

  function collectAssertions() {
    var result = [];
    $('#assertionRows .assertion-row').each(function () {
      var source = $(this).find('.assertion-source').val();
      var comparator = $(this).find('.assertion-comparator').val();
      var item = {
        name: $(this).find('.assertion-name').val().trim(),
        source: source,
        comparator: comparator,
        value_type: comparator === 'is_none' || comparator === 'is_not_none' ? '' : $(this).find('.assertion-value-type').val()
      };
      if (source === 'body_json') item.jsonpath = $(this).find('.assertion-jsonpath').val().trim();
      if (source === 'headers') item.header = $(this).find('.assertion-header').val().trim();
      if (comparator !== 'is_none' && comparator !== 'is_not_none') item.expected = $(this).find('.assertion-expected').val();
      result.push(item);
    });
    return result;
  }

  function syncCurrentStep() {
    if (selectedIndex < 0 || !steps[selectedIndex] || !$('#stepName').length) return;
    var step = steps[selectedIndex];
    step.name = $('#stepName').val().trim();
    if (step.step_type === 'wait') {
      step.wait_seconds = Number($('#waitSeconds').val());
      return;
    }
    step.source_type = $('#stepSource').val();
    step.interface_id = Number($('#stepInterface').val()) || null;
    step.timeout_seconds = Number($('#stepTimeout').val());
    step.method = $('#stepMethod').val();
    step.url = $('#stepUrl').val().trim();
    if ($('#paramsRows').length) step.params = rowsToObject('#paramsRows');
    if ($('#headersRows').length) step.headers = rowsToObject('#headersRows');
    if ($('#bodyRows').length) step.body = rowsToObject('#bodyRows');
    if ($('#bodyText').length) {
      var bodyText = $('#bodyText').val();
      if (step.body_type === 'json') {
        try { step.body = bodyText.trim() ? JSON.parse(bodyText) : {}; }
        catch (error) { throw new Error('Body 不是合法 JSON：' + error.message); }
      } else {
        step.body = bodyText;
      }
    }
    if ($('#extractorRows').length) step.extractors = collectExtractors();
    if ($('#assertionRows').length) step.assertions = collectAssertions();
  }

  function selectStep(index) {
    try { syncCurrentStep(); } catch (error) { AppToast.error(error.message); return; }
    selectedIndex = index;
    renderAll();
  }

  function addStep(step) {
    try { syncCurrentStep(); } catch (error) { AppToast.error(error.message); return; }
    steps.push(step);
    selectedIndex = steps.length - 1;
    renderAll();
  }

  function loadInterfaceGroups(projectId) {
    interfaceGroups = [];
    interfaceMap = {};
    return $.ajax({url: '/api/data-factory/interface-options', method: 'POST', contentType: 'application/json', data: JSON.stringify({project_id: projectId || null})}).done(function (resp) {
      interfaceGroups = resp.data || [];
      interfaceGroups.forEach(function (group) {
        (group.interfaces || []).forEach(function (item) { interfaceMap[item.id] = item; });
      });
      if (selectedIndex >= 0) renderStepConfig();
    });
  }

  function fillFromInterface(item) {
    if (!item || selectedIndex < 0) return;
    var step = steps[selectedIndex];
    step.interface_id = item.id;
    step.name = item.name;
    step.method = item.method;
    step.url = item.url;
    step.body_type = item.body_type;
    step.params = $.extend(true, {}, item.params || {});
    step.headers = $.extend(true, {}, item.headers || {});
    step.body = $.extend(true, Array.isArray(item.body) ? [] : {}, item.body == null ? {} : item.body);
    renderAll();
  }

  function collectPayload() {
    syncCurrentStep();
    return {
      factory_id: factoryId ? Number(factoryId) : null,
      name: $('#factoryName').val().trim(),
      project_id: Number($('#factoryProject').val()) || null,
      environment_id: Number($('#factoryEnvironment').val()) || null,
      description: $('#factoryDescription').val().trim(),
      default_loop_count: Number($('#factoryLoopCount').val()),
      default_concurrency: Number($('#factoryConcurrency').val()),
      steps: steps.map(function (step) {
        var result = $.extend(true, {}, step);
        delete result._key;
        delete result._tab;
        return result;
      })
    };
  }

  function submitFactory(payload, executeAfter) {
    var buttons = $('#saveFactoryButton,#runFactoryButton').prop('disabled', true);
    $.ajax({url: factoryId ? '/api/data-factory/save' : '/api/data-factory/create', method: 'POST', contentType: 'application/json', data: JSON.stringify(payload)})
      .done(function (resp) {
        factoryId = resp.data.id;
        if (!executeAfter) {
          window.location.href = '/data-factories/' + factoryId + '/edit';
          return;
        }
        $.ajax({url: '/api/data-factory/execute', method: 'POST', contentType: 'application/json', data: JSON.stringify({factory_id: factoryId, environment_id: payload.environment_id, loop_count: payload.default_loop_count, concurrency: payload.default_concurrency})})
          .done(function (runResp) { window.location.href = '/data-factories/runs/' + runResp.data.run_id; })
          .fail(function (xhr) { AppToast.error((xhr.responseJSON && xhr.responseJSON.message) || '启动生成失败'); buttons.prop('disabled', false); });
      })
      .fail(function (xhr) { AppToast.error((xhr.responseJSON && xhr.responseJSON.message) || '保存失败'); buttons.prop('disabled', false); });
  }

  function saveFactory(executeAfter) {
    var payload;
    try { payload = collectPayload(); } catch (error) { AppToast.error(error.message); return; }
    if (!executeAfter) {
      submitFactory(payload, false);
      return;
    }
    AppDialog.confirm({
      title: '确认立即生成数据',
      message: '造数接口可能产生不可逆数据，确认保存并立即执行？',
      confirmText: '立即生成',
      tone: 'warning'
    }).then(function (confirmed) {
      if (confirmed) submitFactory(payload, true);
    });
  }

  function showDebugResult(data, stepKey) {
    debugResultCache[stepKey] = data;
    if (selectedIndex >= 0 && steps[selectedIndex]._key === stepKey) {
      renderDebugResult(data);
    }
  }

  function renderCachedDebugResult(step) {
    var data = debugResultCache[step._key];
    if (data) renderDebugResult(data);
  }

  function renderDebugResult(data) {
    var response = data.response_snapshot || {};
    var paths = (data.jsonpaths || []).map(function (path) {
      return '<button class="btn btn-sm btn-outline-secondary jsonpath-choice" data-path="' + escapeHtml(path) + '" type="button">' + escapeHtml(path) + '</button>';
    }).join('') || '<span class="text-secondary small">响应不是 JSON，暂无可点选路径</span>';
    var html = '<div class="d-flex justify-content-between align-items-center mb-2"><strong>调试响应</strong><span class="badge text-bg-' + (data.success ? 'success' : 'danger') + '">' + (data.success ? '成功' : '失败') + '</span></div>' + (data.error_message ? '<div class="alert alert-danger py-2">' + escapeHtml(data.error_message) + '</div>' : '') + '<div class="small text-secondary mb-2">状态码 ' + escapeHtml(response.status_code) + ' · ' + escapeHtml(response.elapsed_ms) + ' ms · ' + escapeHtml(response.body_length) + ' B</div><pre class="snapshot-pre bg-light border rounded p-3">' + escapeHtml(response.body || '') + '</pre><div class="fw-semibold small mb-2">JSONPath 点选</div><div class="d-flex flex-wrap gap-2">' + paths + '</div>';
    $('#debugResult').html(html).show();
  }

  function focusedJsonpathState(step) {
    if (!focusedJsonpathByStep[step._key]) {
      focusedJsonpathByStep[step._key] = {extractors: null, assertions: null};
    }
    return focusedJsonpathByStep[step._key];
  }

  function preferredJsonpathInput(selector, rowSelector, preferredIndex) {
    var inputs = $(selector);
    if (preferredIndex !== null && preferredIndex >= 0) {
      var focusedInput = $(rowSelector).eq(preferredIndex).find(selector.split(' ').pop());
      if (focusedInput.is(':visible')) return focusedInput.first();
    }
    return inputs.last();
  }

  function fillJsonpathFromPicker(path) {
    if (selectedIndex < 0 || !steps[selectedIndex]) return;
    var step = steps[selectedIndex];
    var focusState = focusedJsonpathState(step);
    var target;
    if (step._tab === 'assertions') {
      target = preferredJsonpathInput(
        '#assertionRows .assertion-jsonpath:visible',
        '#assertionRows .assertion-row',
        focusState.assertions
      );
      if (!target.length) return;
      target.val(path).trigger('input').focus();
      step.assertions = collectAssertions();
      return;
    }
    if (step._tab !== 'extractors') return;
    target = preferredJsonpathInput(
      '#extractorRows .extractor-jsonpath:visible',
      '#extractorRows .extractor-row',
      focusState.extractors
    );
    if (!target.length) {
      step.extractors = collectExtractors();
      step.extractors.push({
        variable_name: '',
        jsonpath: path,
        required: false
      });
      focusState.extractors = step.extractors.length - 1;
      renderStepConfig();
      target = $('#extractorRows .extractor-jsonpath:visible').last();
      target.focus();
      return;
    }
    target.val(path).trigger('input').focus();
    step.extractors = collectExtractors();
  }

  $('#flowCanvas').on('click', '.flow-node', function (event) {
    if ($(event.target).closest('button').length) return;
    selectStep(Number($(this).data('index')));
  });
  $('#flowCanvas').on('click', '#addRequestStep', function () { addStep(newRequestStep()); });
  $('#flowCanvas').on('click', '#addWaitStep', function () { addStep(newWaitStep()); });
  $('#flowCanvas').on('click', '.delete-step', function () {
    var index = Number($(this).closest('.flow-node').data('index'));
    AppDialog.confirm({
      title: '删除流程步骤',
      message: '确认删除该步骤？该步骤的请求配置、提取器和断言将一并删除。',
      confirmText: '确认删除',
      tone: 'danger'
    }).then(function (confirmed) {
      if (!confirmed) return;
      var removedStep = steps[index];
      delete debugResultCache[removedStep._key];
      delete focusedJsonpathByStep[removedStep._key];
      steps.splice(index, 1);
      if (!steps.length) selectedIndex = -1;
      else if (selectedIndex >= steps.length) selectedIndex = steps.length - 1;
      else if (index < selectedIndex) selectedIndex -= 1;
      renderAll();
    });
  });
  $('#flowCanvas').on('click', '.move-step-up,.move-step-down', function () {
    var index = Number($(this).closest('.flow-node').data('index'));
    var target = $(this).hasClass('move-step-up') ? index - 1 : index + 1;
    if (target < 0 || target >= steps.length) return;
    try { syncCurrentStep(); } catch (error) { AppToast.error(error.message); return; }
    var moving = steps.splice(index, 1)[0];
    steps.splice(target, 0, moving);
    selectedIndex = selectedIndex === index ? target : (selectedIndex === target ? index : selectedIndex);
    renderAll();
  });

  $('#stepConfig').on('input', '#stepName,#waitSeconds,#stepUrl,#stepTimeout', function () {
    try { syncCurrentStep(); renderFlow(); } catch (error) { return; }
  });
  $('#stepConfig').on('change', '#stepSource', function () {
    if ($(this).val() === 'interface' && !$('#factoryProject').val()) {
      AppToast.warning('请先选择所属项目');
      $(this).val('custom');
    }
    steps[selectedIndex].source_type = $(this).val();
    if ($(this).val() === 'custom') steps[selectedIndex].interface_id = null;
    renderStepConfig();
  });
  $('#stepConfig').on('change', '#stepInterface', function () { fillFromInterface(interfaceMap[Number($(this).val())]); });
  $('#stepConfig').on('change', '#stepMethod', function () { steps[selectedIndex].method = $(this).val(); renderFlow(); });
  $('#stepConfig').on('click', '.factory-tab', function () {
    try { syncCurrentStep(); } catch (error) { AppToast.error(error.message); return; }
    steps[selectedIndex]._tab = $(this).data('tab');
    renderStepConfig();
  });
  $('#stepConfig').on('click', '.add-kv', function () {
    var kind = $(this).data('kind');
    $('#' + kind + 'Rows').append(kvRows(kind, {}));
  });
  $('#stepConfig').on('click', '.remove-kv', function () {
    var container = $(this).parent().parent();
    $(this).closest('.factory-kv-row').remove();
    if (!container.find('.factory-kv-row').length) container.append(kvRows(container.attr('id').replace('Rows', ''), {}));
  });
  $('#stepConfig').on('click', '.body-type', function () {
    try { syncCurrentStep(); } catch (error) { AppToast.error(error.message); return; }
    steps[selectedIndex].body_type = $(this).data('value');
    if (steps[selectedIndex].body_type === 'none') steps[selectedIndex].body = {};
    renderStepConfig();
  });
  $('#stepConfig').on('click', '#beautifyBody', function () {
    try { $('#bodyText').val(prettyJson(JSON.parse($('#bodyText').val() || '{}'))); }
    catch (error) { AppToast.error('Body 不是合法 JSON：' + error.message); }
  });
  $('#stepConfig').on('click', '#addExtractor', function () {
    try { syncCurrentStep(); } catch (error) { AppToast.error(error.message); return; }
    steps[selectedIndex].extractors.push({variable_name: '', jsonpath: '', required: false});
    renderStepConfig();
  });
  $('#stepConfig').on('click', '.remove-extractor', function () {
    var index = $(this).closest('.extractor-row').index();
    steps[selectedIndex].extractors = collectExtractors();
    steps[selectedIndex].extractors.splice(index, 1);
    focusedJsonpathState(steps[selectedIndex]).extractors = null;
    renderStepConfig();
  });
  $('#stepConfig').on('click', '#addAssertion', function () {
    try { syncCurrentStep(); } catch (error) { AppToast.error(error.message); return; }
    steps[selectedIndex].assertions.push({name: '', source: 'body_json', jsonpath: '', comparator: 'equals', value_type: 'string', expected: ''});
    renderStepConfig();
  });
  $('#stepConfig').on('click', '.remove-assertion', function () {
    var index = $(this).closest('.assertion-row').index();
    steps[selectedIndex].assertions = collectAssertions();
    steps[selectedIndex].assertions.splice(index, 1);
    focusedJsonpathState(steps[selectedIndex]).assertions = null;
    renderStepConfig();
  });
  $('#stepConfig').on('change', '.assertion-source,.assertion-comparator', function () {
    steps[selectedIndex].assertions = collectAssertions();
    renderStepConfig();
  });
  $('#stepConfig').on('focusin', '.extractor-jsonpath', function () {
    focusedJsonpathState(steps[selectedIndex]).extractors = $(this).closest('.extractor-row').index();
  });
  $('#stepConfig').on('focusin', '.assertion-jsonpath', function () {
    focusedJsonpathState(steps[selectedIndex]).assertions = $(this).closest('.assertion-row').index();
  });
  $('#stepConfig').on('click', '.jsonpath-choice', function () {
    fillJsonpathFromPicker($(this).data('path'));
  });
  $('#stepConfig').on('click', '#debugStep', function () {
    var step;
    try { syncCurrentStep(); step = $.extend(true, {}, steps[selectedIndex]); } catch (error) { AppToast.error(error.message); return; }
    var stepKey = steps[selectedIndex]._key;
    var button = $(this).prop('disabled', true).text('发送中...');
    $.ajax({url: '/api/data-factory/debug-request', method: 'POST', contentType: 'application/json', data: JSON.stringify({project_id: Number($('#factoryProject').val()) || null, environment_id: Number($('#factoryEnvironment').val()) || null, step_config: step})})
      .done(function (resp) { showDebugResult(resp.data, stepKey); })
      .fail(function (xhr) { AppToast.error((xhr.responseJSON && xhr.responseJSON.message) || '调试失败'); })
      .always(function () { button.prop('disabled', false).text('发送'); });
  });

  function applyProjectChange(nextProject) {
    if (nextProject !== previousProjectId) {
      steps.forEach(function (item) {
        if (item.step_type === 'request' && item.source_type === 'interface') item.interface_id = null;
      });
    }
    previousProjectId = nextProject;
    loadInterfaceGroups(nextProject);
  }

  $('#factoryProject').on('change', function () {
    var projectSelect = $(this);
    var nextProject = String(projectSelect.val() || '');
    var hasReferences = steps.some(function (item) { return item.step_type === 'request' && item.source_type === 'interface' && item.interface_id; });
    if (hasReferences && nextProject !== previousProjectId) {
      AppDialog.confirm({
        title: '切换所属项目',
        message: '切换项目会清除当前流程中引用的接口库关联，是否继续？',
        confirmText: '继续切换',
        tone: 'warning'
      }).then(function (confirmed) {
        if (!confirmed) {
          projectSelect.val(previousProjectId);
          return;
        }
        applyProjectChange(nextProject);
      });
      return;
    }
    applyProjectChange(nextProject);
  });
  $('#saveFactoryButton').on('click', function () { saveFactory(false); });
  $('#runFactoryButton').on('click', function () { saveFactory(true); });

  function fillFactory(item) {
    $('#factoryName').val(item.name);
    $('#factoryProject').val(item.project_id || '');
    $('#factoryEnvironment').val(item.environment_id);
    $('#factoryDescription').val(item.description || '');
    $('#factoryLoopCount').val(item.default_loop_count);
    $('#factoryConcurrency').val(item.default_concurrency);
    previousProjectId = String(item.project_id || '');
    steps = (item.steps || []).map(normalizeStep);
    selectedIndex = steps.length ? 0 : -1;
    loadInterfaceGroups(item.project_id).done(renderAll);
  }

  $.post({url: '/api/data-factory/options', contentType: 'application/json', data: '{}'}).done(function (resp) {
    optionData = resp.data || {};
    $('#factoryProject').append((optionData.projects || []).map(function (item) { return '<option value="' + item.id + '">' + escapeHtml(item.name) + '</option>'; }).join(''));
    AppSelect.fill('#factoryEnvironment', optionData.environments, {
      label: function (item) { return item.name + (item.base_url ? ' - ' + item.base_url : ''); },
      emptyText: '暂无环境',
      emptyHint: '暂无执行环境，请先到「环境与变量管理」创建'
    });
    if (factoryId) {
      $.ajax({url: '/api/data-factory/detail', method: 'POST', contentType: 'application/json', data: JSON.stringify({factory_id: Number(factoryId)})}).done(function (detailResp) { fillFactory(detailResp.data); });
    } else {
      steps = [newRequestStep()];
      selectedIndex = 0;
      renderAll();
    }
  });
}());
