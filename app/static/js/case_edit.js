var caseOptions = {projects: [], environments: [], interfaces: []};
var currentCase = null;
var currentBodyType = 'none';
var lastFocusedAssertionJsonpath = null;
var lastFocusedExtractorJsonpath = null;

function escapeHtml(text) {
  return $('<div>').text(text === null || text === undefined ? '' : String(text)).html();
}

function prettyJson(value) {
  return JSON.stringify(value === null || value === undefined ? {} : value, null, 2);
}

function parseJsonText(text) {
  var value = text || '';
  return value.trim() ? JSON.parse(value) : {};
}

function tryPrettyJsonText(text) {
  if (text === null || text === undefined || text === '') {
    return {matched: false, value: text || ''};
  }
  if (typeof text !== 'string') {
    return {matched: true, value: prettyJson(text)};
  }
  try {
    return {matched: true, value: JSON.stringify(JSON.parse(text), null, 2)};
  } catch (err) {
    return {matched: false, value: text};
  }
}

function formatResponseBody(response, responseContext, runner) {
  response = response || {};
  responseContext = responseContext || {};
  runner = runner || {};

  if (responseContext.body_json !== null && responseContext.body_json !== undefined) {
    return prettyJson(responseContext.body_json);
  }

  var rawBody = response.body;
  if (rawBody === null || rawBody === undefined) {
    rawBody = responseContext.body_text;
  }
  if (rawBody === null || rawBody === undefined || rawBody === '') {
    var error = runner.error || responseContext.error;
    return error ? 'Error: ' + error : '-';
  }

  var parsed = tryPrettyJsonText(rawBody);
  return parsed.value || '-';
}

function showCaseError(message) {
  $('#caseError').removeClass('d-none').text(message || '操作失败');
}

function clearCaseError() {
  $('#caseError').addClass('d-none').text('');
}

function postJson(url, payload, callback) {
  return $.ajax({
    url: url,
    method: 'POST',
    contentType: 'application/json',
    data: JSON.stringify(payload || {})
  }).done(callback);
}

function loadOptions() {
  return postJson('/api/test-case/options', {}, function (resp) {
    caseOptions = resp.data || {projects: [], environments: [], interfaces: []};
    renderProjectOptions();
    renderEnvironmentOptions();
    renderMethodOptions();
    renderInterfaceOptions();
  });
}

function renderProjectOptions() {
  $('#projectSelect').html(caseOptions.projects.map(function (item) {
    return '<option value="' + item.id + '">' + escapeHtml(item.name) + '</option>';
  }).join(''));
}

function renderEnvironmentOptions() {
  $('#environmentSelect').html(caseOptions.environments.map(function (item) {
    var baseUrl = item.base_url ? ' - ' + item.base_url : '';
    return '<option value="' + item.id + '">' + escapeHtml(item.name + baseUrl) + '</option>';
  }).join(''));
}

function renderMethodOptions() {
  var methods = ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS'];
  $('#methodSelect').html(methods.map(function (method) {
    return '<option value="' + method + '">' + method + '</option>';
  }).join(''));
}

function renderInterfaceOptions() {
  var projectId = Number($('#projectSelect').val());
  var options = caseOptions.interfaces.filter(function (item) {
    return Number(item.project_id) === projectId && item.interface_type === 'http';
  }).map(function (item) {
    return '<option value="' + item.id + '">' + escapeHtml(item.name + ' [' + item.interface_type + ']') + '</option>';
  }).join('');
  $('#interfaceSelect').html(options);
  applySelectedInterface();
}

function selectedInterface() {
  var interfaceId = Number($('#interfaceSelect').val());
  return caseOptions.interfaces.find(function (item) { return Number(item.id) === interfaceId; });
}

function applySelectedInterface() {
  var item = selectedInterface();
  if (!item) {
    return;
  }
  $('#methodSelect').val((item.method || 'GET').toUpperCase());
  $('#requestUrl').val(item.url || '');
  setBodyType(item.body_type || 'none');
  if (!currentCase) {
    renderKvRows('#paramsTable', objectToRows(item.params_template || {}, true));
    renderHeaders(objectToRows(item.headers_template || {}, true));
    fillBodyFromValue(item.body_template || {});
  }
}

function loadCaseIfNeeded() {
  var caseId = $('#caseId').val();
  if (!caseId) {
    addKvRow('#paramsTable');
    addPresetHeaders();
    renderAssertions([defaultStatusAssertion()]);
    renderExtractors([{}]);
    applyInterfacePrefill();
    updateCounts();
    return $.Deferred().resolve().promise();
  }
  return postJson('/api/test-case/detail', {case_id: Number(caseId)}, function (resp) {
    currentCase = resp.data;
    fillCase(currentCase);
  });
}

function applyInterfacePrefill() {
  var interfaceId = Number($('#prefillInterfaceId').val());
  if (!interfaceId) {
    return;
  }
  var item = caseOptions.interfaces.find(function (option) {
    return Number(option.id) === interfaceId;
  });
  if (!item) {
    showCaseError('预填接口不存在或已被删除');
    return;
  }
  $('#projectSelect').val(item.project_id);
  renderInterfaceOptions();
  $('#interfaceSelect').val(item.id);
  applySelectedInterface();
  $('#caseName').val(item.name || '');
}

function fillCase(item) {
  $('#projectSelect').val(item.project_id);
  renderInterfaceOptions();
  $('#interfaceSelect').val(item.interface_id);
  var iface = selectedInterface();
  $('#methodSelect').val((item.method || (iface && iface.method) || 'GET').toUpperCase());
  $('#requestUrl').val(item.url || (iface && iface.url) || '');
  $('#environmentSelect').val(item.environment_id || $('#environmentSelect').val());
  $('#caseName').val(item.name);
  $('#timeoutSeconds').val(item.timeout_seconds || 30);
  $('#caseActive').prop('checked', item.is_active);
  setBodyType(item.body_type || (iface && iface.body_type) || 'none');
  renderHeaders(objectToRows(item.headers_override || {}, true));
  renderKvRows('#paramsTable', objectToRows(item.request_params || {}, true));
  fillBodyFromValue(item.body_override || {});
  renderAssertions(item.assertions || [defaultStatusAssertion()]);
  renderExtractors(item.extractors || [{}]);
  updateCounts();
}

function defaultStatusAssertion() {
  return {name: 'status_code', source: 'status_code', comparator: 'equals', expected: '200', value_type: 'int'};
}

function objectToRows(value, enabled) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return [];
  }
  return Object.keys(value).map(function (key) {
    return {enabled: enabled !== false, key: key, value: value[key], description: ''};
  });
}

function rowsToObject(selector) {
  var data = {};
  $(selector + ' tbody tr').each(function () {
    var enabled = $(this).find('.kv-check').is(':checked');
    var key = $(this).find('.kv-key').val();
    var value = $(this).find('.kv-value').val();
    if (enabled && key) {
      data[key] = value;
    }
  });
  return data;
}

function addKvRow(selector, row) {
  row = row || {};
  var html = '<tr>' +
    '<td class="kv-enabled"><input class="form-check-input kv-check" type="checkbox"' + (row.enabled === false ? '' : ' checked') + '></td>' +
    '<td><input class="form-control kv-key" placeholder="Key" value="' + escapeHtml(row.key || '') + '"></td>' +
    '<td><input class="form-control kv-value" placeholder="Value，支持 {{变量}} 和 ${提取变量}" value="' + escapeHtml(row.value || '') + '"></td>' +
    '<td><input class="form-control kv-description" placeholder="Description" value="' + escapeHtml(row.description || '') + '"></td>' +
    '<td class="kv-action"><button type="button" class="btn btn-sm btn-outline-danger remove-row">删除</button></td>' +
  '</tr>';
  $(selector + ' tbody').append(html);
  if (selector === '#headersTable') {
    AppCombobox.attach($(selector + ' tbody tr').last().find('.kv-key')[0], {
      options: AppCombobox.headerOptions,
      allowCustom: true,
      emptyText: '没有匹配的常用 Header，可直接输入',
      customText: '使用 Header：'
    });
  }
}

function renderKvRows(selector, rows) {
  AppCombobox.destroyWithin($(selector + ' tbody')[0]);
  $(selector + ' tbody').empty();
  (rows && rows.length ? rows : [{}]).forEach(function (row) { addKvRow(selector, row); });
}

function renderHeaders(rows) {
  renderKvRows('#headersTable', rows && rows.length ? rows : []);
}

function addPresetHeaders() {
  var existing = rowsToObject('#headersTable');
  [
    {key: 'Accept', value: '*/*'},
    {key: 'Accept-Encoding', value: 'gzip, deflate, br'},
    {key: 'Connection', value: 'keep-alive'},
    {key: 'User-Agent', value: 'ApiTestPlatform/1.0'}
  ].forEach(function (item) {
    if (!Object.prototype.hasOwnProperty.call(existing, item.key)) {
      addKvRow('#headersTable', {enabled: true, key: item.key, value: item.value});
    }
  });
  updateCounts();
}

function setBodyType(type) {
  if (type === 'form') {
    type = 'x-www-form-urlencoded';
  }
  if (type === 'raw') {
    type = 'json';
  }
  currentBodyType = type || 'none';
  $('.body-type').removeClass('active');
  $('.body-type[data-body-type="' + currentBodyType + '"]').addClass('active');
  $('#bodyNone').toggle(currentBodyType === 'none');
  $('#bodyKv').toggle(currentBodyType === 'form-data' || currentBodyType === 'x-www-form-urlencoded');
  $('#bodyJson').toggle(currentBodyType === 'json');
}

function fillBodyFromValue(value) {
  if (currentBodyType === 'form-data' || currentBodyType === 'x-www-form-urlencoded') {
    renderKvRows('#bodyTable', objectToRows(value || {}, true));
  } else if (currentBodyType === 'json') {
    $('#bodyJsonText').val(prettyJson(value || {}));
  }
}

function collectBody() {
  if (currentBodyType === 'none') {
    return {};
  }
  if (currentBodyType === 'form-data' || currentBodyType === 'x-www-form-urlencoded') {
    return rowsToObject('#bodyTable');
  }
  if (currentBodyType === 'json') {
    var value = $('#bodyJsonText').val();
    return parseJsonText(value);
  }
  return {};
}

function beautifyBodyJson() {
  clearCaseError();
  try {
    $('#bodyJsonText').val(prettyJson(parseJsonText($('#bodyJsonText').val())));
  } catch (err) {
    showCaseError('JSON 格式错误：' + err.message);
  }
}

function addAssertion(item) {
  item = item || {};
  var html = '<div class="border rounded p-3 mb-2 assertion-item">' +
    '<div class="row g-2">' +
      '<div class="col-md-2"><input class="form-control assertion-name" placeholder="断言名称" value="' + escapeHtml(item.name || '') + '"></div>' +
      '<div class="col-md-2"><select class="form-select assertion-source">' + sourceOptions(item.source) + '</select></div>' +
      '<div class="col-md-2 assertion-jsonpath-field"><input class="form-control assertion-jsonpath" placeholder="JSONPath，如 $.data.id" value="' + escapeHtml(item.jsonpath || '') + '"></div>' +
      '<div class="col-md-2 assertion-header-field"><input class="form-control assertion-header" placeholder="响应头名称，如 Content-Type" value="' + escapeHtml(item.header || '') + '"></div>' +
      '<div class="col-md-2"><select class="form-select assertion-comparator">' + comparatorOptions(item.comparator) + '</select></div>' +
      '<div class="col-md-2 assertion-value-type-field"><select class="form-select assertion-value-type">' + valueTypeOptions(item.value_type) + '</select></div>' +
      '<div class="col-md-1"><button type="button" class="btn btn-outline-danger w-100 remove-item">删</button></div>' +
      '<div class="col-12"><input class="form-control assertion-expected" placeholder="期望值" value="' + escapeHtml(item.expected === null || item.expected === undefined ? '' : item.expected) + '"></div>' +
    '</div>' +
  '</div>';
  $('#assertionList').append(html);
  updateAssertionFields($('#assertionList .assertion-item').last());
  updateCounts();
}

function renderAssertions(items) {
  $('#assertionList').empty();
  (items.length ? items : [defaultStatusAssertion()]).forEach(addAssertion);
}

function sourceOptions(selected) {
  var values = ['status_code', 'headers', 'body_json', 'body_text', 'body_type', 'body_length', 'elapsed_ms', 'ws_message'];
  return values.map(function (value) {
    return '<option value="' + value + '"' + (value === selected ? ' selected' : '') + '>' + value + '</option>';
  }).join('');
}

function comparatorOptions(selected) {
  selected = selected || 'equals';
  return (caseOptions.assertion_comparators || []).map(function (item) {
    return '<option value="' + item.value + '"' + (item.value === selected ? ' selected' : '') + '>' + escapeHtml(item.label) + '</option>';
  }).join('');
}

function valueTypeOptions(selected) {
  selected = selected === 'raw' ? '' : (selected || '');
  return (caseOptions.assertion_value_types || []).map(function (item) {
    return '<option value="' + item.value + '"' + (item.value === selected ? ' selected' : '') + '>' + escapeHtml(item.label) + '</option>';
  }).join('');
}

function updateAssertionFields($item) {
  var source = $item.find('.assertion-source').val();
  var comparator = $item.find('.assertion-comparator').val();
  var withoutExpected = comparator === 'is_none' || comparator === 'is_not_none';
  $item.find('.assertion-jsonpath-field').toggle(source === 'body_json');
  $item.find('.assertion-header-field').toggle(source === 'headers');
  $item.find('.assertion-expected')
    .prop('disabled', withoutExpected)
    .attr('placeholder', withoutExpected ? '该比较器不需要期望值' : '期望值');
  $item.find('.assertion-value-type').prop('disabled', withoutExpected);
}

function collectAssertions() {
  var items = [];
  $('.assertion-item').each(function () {
    var source = $(this).find('.assertion-source').val();
    var comparator = $(this).find('.assertion-comparator').val();
    var item = {
      name: $(this).find('.assertion-name').val(),
      source: source,
      comparator: comparator,
      value_type: comparator === 'is_none' || comparator === 'is_not_none'
        ? ''
        : $(this).find('.assertion-value-type').val()
    };
    if (source === 'body_json') {
      item.jsonpath = $(this).find('.assertion-jsonpath').val();
    }
    if (source === 'headers') {
      item.header = $(this).find('.assertion-header').val();
    }
    if (comparator !== 'is_none' && comparator !== 'is_not_none') {
      item.expected = $(this).find('.assertion-expected').val();
    }
    if (item.source || item.expected || item.jsonpath) {
      items.push(item);
    }
  });
  return items;
}

function validateAssertions(assertions) {
  for (var index = 0; index < assertions.length; index += 1) {
    var item = assertions[index];
    if (item.source === 'headers' && !(item.header || '').trim()) {
      return '第 ' + (index + 1) + ' 条断言的响应头名称不能为空';
    }
    if (item.source === 'body_json' && !(item.jsonpath || '').trim()) {
      return '第 ' + (index + 1) + ' 条断言的 JSONPath 不能为空';
    }
  }
  return '';
}

function addExtractor(item) {
  item = item || {};
  var html = '<div class="border rounded p-3 mb-2 extractor-item">' +
    '<div class="row g-2">' +
      '<div class="col-md-5"><input class="form-control extractor-jsonpath" placeholder="JSONPath，如 $.data.token" value="' + escapeHtml(item.jsonpath || '') + '"></div>' +
      '<div class="col-md-4"><input class="form-control extractor-name" placeholder="变量名，如 token；后续用 ${token}" value="' + escapeHtml(item.variable_name || '') + '"></div>' +
      '<div class="col-md-2 d-flex align-items-center"><div class="form-check"><input class="form-check-input extractor-required" type="checkbox"' + (item.required ? ' checked' : '') + '><label class="form-check-label">必填</label></div></div>' +
      '<div class="col-md-1"><button type="button" class="btn btn-outline-danger w-100 remove-item">删</button></div>' +
    '</div>' +
  '</div>';
  $('#extractorList').append(html);
}

function renderExtractors(items) {
  $('#extractorList').empty();
  (items.length ? items : [{}]).forEach(addExtractor);
}

function collectExtractors() {
  var items = [];
  $('.extractor-item').each(function () {
    var item = {
      jsonpath: $(this).find('.extractor-jsonpath').val(),
      variable_name: $(this).find('.extractor-name').val(),
      required: $(this).find('.extractor-required').is(':checked')
    };
    if (item.jsonpath || item.variable_name) {
      items.push(item);
    }
  });
  return items;
}

function collectPayload() {
  return {
    project_id: Number($('#projectSelect').val()),
    interface_id: Number($('#interfaceSelect').val()),
    environment_id: Number($('#environmentSelect').val()) || null,
    method: $('#methodSelect').val(),
    url: $('#requestUrl').val(),
    body_type: currentBodyType,
    name: $('#caseName').val() || selectedCaseName(),
    request_params: rowsToObject('#paramsTable'),
    headers_override: rowsToObject('#headersTable'),
    body_override: collectBody(),
    assertions: collectAssertions(),
    extractors: collectExtractors(),
    timeout_seconds: Number($('#timeoutSeconds').val() || 30),
    description: '',
    is_active: true
  };
}

function selectedCaseName() {
  var iface = selectedInterface();
  return iface ? iface.name : '未命名用例';
}

function saveCase() {
  clearCaseError();
  var payload;
  try {
    payload = collectPayload();
  } catch (err) {
    showCaseError('输入格式错误：' + err.message);
    return $.Deferred().reject().promise();
  }
  var assertionError = validateAssertions(payload.assertions);
  if (assertionError) {
    showCaseError(assertionError);
    return $.Deferred().reject().promise();
  }

  var id = $('#caseId').val();
  if (id) {
    payload.case_id = Number(id);
  }
  return $.ajax({
    url: id ? '/api/test-case/save' : '/api/test-case/create',
    method: 'POST',
    contentType: 'application/json',
    data: JSON.stringify(payload)
  }).done(function (resp) {
    $('#caseId').val(resp.data.id);
    currentCase = resp.data;
  }).fail(function (xhr) {
    showCaseError((xhr.responseJSON && xhr.responseJSON.message) || '保存失败');
  });
}

function debugCase() {
  saveCase().done(function (resp) {
    var caseId = (resp.data && resp.data.id) || $('#caseId').val();
    $('#debugStatus').removeClass().addClass('badge text-bg-secondary').text('发送中');
    $('#responseEmpty').addClass('d-none');
    $('#debugBody').removeClass('d-none').text('请求发送中...');
    $.ajax({
      url: '/api/test-case/debug',
      method: 'POST',
      contentType: 'application/json',
      data: JSON.stringify({case_id: Number(caseId), environment_id: Number($('#environmentSelect').val())})
    }).done(function (debugResp) {
      renderDebug(debugResp.data || {});
    }).fail(function (xhr) {
      showCaseError((xhr.responseJSON && xhr.responseJSON.message) || '调试失败');
    });
  });
}

function renderDebug(result) {
  var runner = result.runner || {};
  var response = runner.response || {};
  var responseContext = runner.response_context || {};
  var status = response.status_code || responseContext.status_code || '-';
  var elapsed = response.elapsed_ms || responseContext.elapsed_ms || responseContext.time_taken_ms || '-';
  var body = formatResponseBody(response, responseContext, runner);
  var size = responseContext.body_length || (body ? body.length : 0);
  $('#debugStatus')
    .removeClass()
    .addClass('badge ' + (runner.success ? 'text-bg-success' : 'text-bg-danger'))
    .text(status === '-' ? 'ERROR' : (status + ' ' + statusText(status)));
  $('#debugElapsed').text(elapsed + ' ms');
  $('#debugSize').text(size + ' B');
  $('#debugHeaders').text(prettyJson(response.headers || responseContext.headers || {}));
  $('#debugBody').removeClass('d-none').text(body || '-');
  $('#responseEmpty').addClass('d-none');
  renderAssertionResults(result.assertions || []);
  renderExtractorResults(result.extractors || []);
  renderJsonpaths(result.jsonpaths || []);
}

function statusText(status) {
  status = Number(status);
  if (status >= 200 && status < 300) {
    return 'OK';
  }
  if (status >= 400) {
    return 'ERROR';
  }
  return '';
}

function renderAssertionResults(items) {
  if (!items.length) {
    $('#assertionResults').text('暂无结果');
    return;
  }
  $('#assertionResults').html(items.map(function (item) {
    var badge = item.passed ? '<span class="badge text-bg-success">通过</span>' : '<span class="badge text-bg-danger">失败</span>';
    var typeInfo = item.actual_type
      ? '<div>类型：实际 ' + escapeHtml(item.actual_type) + ' / 要求 ' + escapeHtml(item.value_type || 'raw') + '</div>'
      : '';
    return '<div class="border rounded p-2 mb-2">' + badge +
      '<div class="mt-1 fw-semibold">' + escapeHtml(item.name || item.source) + '</div>' +
      '<div>比较器：' + escapeHtml(item.comparator_label || item.comparator) + '</div>' +
      '<div>实际值：' + escapeHtml(JSON.stringify(item.actual)) + '</div>' +
      '<div>期望值：' + escapeHtml(JSON.stringify(item.expected)) + '</div>' +
      typeInfo +
      '<div>' + escapeHtml(item.message) + '</div>' +
    '</div>';
  }).join(''));
}

function renderExtractorResults(items) {
  if (!items.length) {
    $('#extractorResults').text('暂无结果');
    return;
  }
  $('#extractorResults').html(items.map(function (item) {
    var badge = item.success ? '<span class="badge text-bg-success">成功</span>' : '<span class="badge text-bg-danger">失败</span>';
    return '<div class="border rounded p-2 mb-2">' + badge +
      '<div class="mt-1">' + escapeHtml(item.variable_name) + ' = ' + escapeHtml(JSON.stringify(item.value)) + '</div>' +
      '<div class="text-secondary">' + escapeHtml(item.jsonpath) + '</div>' +
      '<div>' + escapeHtml(item.message) + '</div>' +
    '</div>';
  }).join(''));
}

function renderJsonpaths(paths) {
  if (!paths.length) {
    $('#jsonpathList').text('暂无路径');
    return;
  }
  $('#jsonpathList').html(paths.map(function (path) {
    return '<button type="button" class="btn btn-sm btn-outline-secondary jsonpath-pill" data-path="' + escapeHtml(path) + '">' + escapeHtml(path) + '</button>';
  }).join(''));
}

function fillJsonpathFromPicker(path) {
  if ($('#assertions-tab').hasClass('active')) {
    var assertionInput = preferredJsonpathInput(
      '#assertionList .assertion-jsonpath:visible',
      lastFocusedAssertionJsonpath
    );
    if (assertionInput.length) {
      assertionInput.val(path).trigger('input').focus();
    }
    return;
  }

  if (!$('#extractors-tab').hasClass('active')) {
    return;
  }

  var extractorInput = preferredJsonpathInput(
    '#extractorList .extractor-jsonpath:visible',
    lastFocusedExtractorJsonpath
  );
  if (!extractorInput.length) {
    addExtractor();
    extractorInput = preferredJsonpathInput(
      '#extractorList .extractor-jsonpath:visible',
      lastFocusedExtractorJsonpath
    );
  }
  extractorInput.val(path).trigger('input').focus();
}

function preferredJsonpathInput(selector, lastFocusedInput) {
  var inputs = $(selector);
  var focusedInput = inputs.filter(function () {
    return this === lastFocusedInput;
  });
  return focusedInput.length ? focusedInput.first() : inputs.last();
}

function updateCounts() {
  $('#headersCount').text(Object.keys(rowsToObject('#headersTable')).length);
  $('#assertionsCount').text(collectAssertions().length);
}

$('#projectSelect').on('change', function () {
  currentCase = null;
  renderInterfaceOptions();
});
$('#interfaceSelect').on('change', function () {
  currentCase = null;
  applySelectedInterface();
});
$('#addParamBtn').on('click', function () { addKvRow('#paramsTable'); });
$('#addBodyParamBtn').on('click', function () { addKvRow('#bodyTable'); });
$('#addHeaderBtn').on('click', function () { addKvRow('#headersTable'); updateCounts(); });
$('#addPresetHeadersBtn').on('click', addPresetHeaders);
$('#addAssertionBtn').on('click', function () { addAssertion(); });
$('#addExtractorBtn').on('click', function () { addExtractor(); });
$('.body-type').on('click', function () { setBodyType($(this).data('body-type')); });
$('#beautifyJsonBtn').on('click', beautifyBodyJson);
$('#headersTable').on('input change', 'input', updateCounts);
$('#assertionList').on('input change', 'input, select', updateCounts);
$('#assertionList').on('change', '.assertion-source, .assertion-comparator', function () {
  updateAssertionFields($(this).closest('.assertion-item'));
});
$('#assertionList').on('focusin', '.assertion-jsonpath', function () {
  lastFocusedAssertionJsonpath = this;
});
$('#extractorList').on('focusin', '.extractor-jsonpath', function () {
  lastFocusedExtractorJsonpath = this;
});
$('#saveCaseBtn').on('click', function () {
  saveCase().done(function () {
    window.location.href = $('#returnTo').val() || '/cases/';
  });
});
$('#debugBtn').on('click', debugCase);
$(document).on('click', '.remove-row', function () {
  var row = $(this).closest('tr')[0];
  AppCombobox.destroyWithin(row);
  $(row).remove();
  updateCounts();
});
$(document).on('click', '.remove-item', function () {
  $(this).closest('.assertion-item, .extractor-item, .ws-step-item').remove();
  updateCounts();
});
$('#jsonpathList').on('click', '.jsonpath-pill', function () {
  var path = $(this).data('path');
  fillJsonpathFromPicker(path);
});

$.when(loadOptions()).done(loadCaseIfNeeded);
