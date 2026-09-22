var interfaceOptions = {projects: [], modules: [], environments: [], methods: []};
var currentBodyType = 'none';
var debugEnvironmentStorageKey = 'interfaceDebugEnvironmentId';
var moduleCombobox = AppCombobox.attach(document.getElementById('moduleInput'), {
  options: [],
  allowCustom: true,
  emptyText: '当前项目暂无模块，可直接输入新模块名称',
  customText: '创建新模块：'
});

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

function showInterfaceError(message) {
  $('#interfaceError').removeClass('d-none').text(message || '操作失败');
}

function clearInterfaceError() {
  $('#interfaceError').addClass('d-none').text('');
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
  return postJson('/api/interface-definition/options', {}, function (resp) {
    interfaceOptions = resp.data || {projects: [], modules: [], environments: [], methods: []};
    renderProjectOptions();
    renderModuleOptions();
    renderEnvironmentOptions();
    renderMethodOptions();
  });
}

function renderProjectOptions() {
  AppSelect.fill('#projectSelect', interfaceOptions.projects, {
    label: function (item) { return item.name; },
    emptyText: '暂无项目',
    emptyHint: '暂无项目，请先到「项目管理」创建'
  });
}

function projectModules() {
  var projectId = Number($('#projectSelect').val());
  return (interfaceOptions.modules || []).filter(function (item) {
    return Number(item.project_id) === projectId;
  });
}

function renderModuleOptions(selectedName) {
  moduleCombobox.setOptions(projectModules().map(function (item) {
    return {value: item.name, label: item.name};
  }));
  if (selectedName !== undefined) {
    $('#moduleInput').val(selectedName || '');
  }
}

function selectedModule() {
  var moduleName = ($('#moduleInput').val() || '').trim().toLowerCase();
  return projectModules().find(function (item) {
    return String(item.name || '').trim().toLowerCase() === moduleName;
  });
}

function renderEnvironmentOptions() {
  AppSelect.fill('#environmentSelect', interfaceOptions.environments, {
    label: function (item) { return item.name + (item.base_url ? ' - ' + item.base_url : ''); },
    emptyText: '暂无环境',
    emptyHint: '暂无执行环境，请先到「环境与变量管理」创建'
  });
  restoreDebugEnvironment();
}

function restoreDebugEnvironment() {
  var savedEnvironmentId = localStorage.getItem(debugEnvironmentStorageKey);
  if (savedEnvironmentId && $('#environmentSelect option[value="' + savedEnvironmentId + '"]').length) {
    $('#environmentSelect').val(savedEnvironmentId);
  }
}

function rememberDebugEnvironment() {
  var environmentId = $('#environmentSelect').val();
  if (environmentId) {
    localStorage.setItem(debugEnvironmentStorageKey, environmentId);
  }
}

function showCurlImportError(message) {
  $('#curlImportError').removeClass('d-none').text(message || 'curl 识别失败');
  $('#curlImportInfo').addClass('d-none').text('');
}

function showCurlImportInfo(message) {
  $('#curlImportInfo').removeClass('d-none').text(message || '');
  $('#curlImportError').addClass('d-none').text('');
}

function clearCurlImportMessage() {
  $('#curlImportError').addClass('d-none').text('');
  $('#curlImportInfo').addClass('d-none').text('');
}

function tokenizeCurl(input) {
  var text = String(input || '').trim()
    .replace(/\\\r?\n/g, ' ')
    .replace(/\^\r?\n/g, ' ')
    .replace(/`\r?\n/g, ' ');
  var tokens = [];
  var current = '';
  var quote = null;
  var escaped = false;

  for (var index = 0; index < text.length; index += 1) {
    var ch = text[index];
    if (escaped) {
      current += ch;
      escaped = false;
      continue;
    }
    if (ch === '\\' && quote !== "'") {
      escaped = true;
      continue;
    }
    if (quote) {
      if (ch === quote) {
        quote = null;
      } else {
        current += ch;
      }
      continue;
    }
    if (ch === '"' || ch === "'") {
      quote = ch;
      continue;
    }
    if (/\s/.test(ch)) {
      if (current !== '') {
        tokens.push(current);
        current = '';
      }
      continue;
    }
    current += ch;
  }

  if (escaped) {
    current += '\\';
  }
  if (quote) {
    throw new Error('引号未闭合，请检查 curl 内容');
  }
  if (current !== '') {
    tokens.push(current);
  }
  return tokens;
}

function parseCurlCommand(input) {
  var tokens = tokenizeCurl(input);
  if (!tokens.length || !/^curl(\.exe)?$/i.test(tokens[0])) {
    throw new Error('请粘贴以 curl 开头的命令');
  }

  var result = {
    method: '',
    url: '',
    headers: {},
    params: {},
    body: {},
    bodyType: 'none',
    matchedEnvironmentId: null,
    matchedBaseUrl: ''
  };
  var bodyParts = [];
  var formParts = [];
  var useQueryData = false;
  var jsonByOption = false;
  var skipValueOptions = {
    '--connect-timeout': true,
    '--max-time': true,
    '--retry': true,
    '--output': true,
    '-o': true,
    '--request-target': true,
    '--proxy': true
  };

  for (var i = 1; i < tokens.length; i += 1) {
    var token = tokens[i];
    var value;
    if (token === '-X' || token === '--request') {
      result.method = (tokens[++i] || '').toUpperCase();
    } else if (token.indexOf('--request=') === 0) {
      result.method = token.substring('--request='.length).toUpperCase();
    } else if (token.indexOf('-X') === 0 && token.length > 2) {
      result.method = token.substring(2).toUpperCase();
    } else if (token === '-H' || token === '--header') {
      appendHeader(result.headers, tokens[++i] || '');
    } else if (token.indexOf('--header=') === 0) {
      appendHeader(result.headers, token.substring('--header='.length));
    } else if (token.indexOf('-H') === 0 && token.length > 2) {
      appendHeader(result.headers, token.substring(2));
    } else if (isCurlDataOption(token)) {
      value = readCurlOptionValue(tokens, i, token);
      i = value.index;
      bodyParts.push(value.value);
    } else if (token.indexOf('--data=') === 0) {
      bodyParts.push(token.substring('--data='.length));
    } else if (token.indexOf('--data-raw=') === 0) {
      bodyParts.push(token.substring('--data-raw='.length));
    } else if (token.indexOf('--data-binary=') === 0) {
      bodyParts.push(token.substring('--data-binary='.length));
    } else if (token.indexOf('--data-urlencode=') === 0) {
      bodyParts.push(token.substring('--data-urlencode='.length));
    } else if (token === '--json') {
      value = readCurlOptionValue(tokens, i, token);
      i = value.index;
      bodyParts.push(value.value);
      jsonByOption = true;
      ensureHeader(result.headers, 'Content-Type', 'application/json');
      ensureHeader(result.headers, 'Accept', 'application/json');
    } else if (token === '-F' || token === '--form' || token === '--form-string') {
      value = readCurlOptionValue(tokens, i, token);
      i = value.index;
      formParts.push(value.value);
    } else if (token.indexOf('--form=') === 0) {
      formParts.push(token.substring('--form='.length));
    } else if (token.indexOf('--form-string=') === 0) {
      formParts.push(token.substring('--form-string='.length));
    } else if (token === '-G' || token === '--get') {
      useQueryData = true;
    } else if (token === '-I' || token === '--head') {
      result.method = 'HEAD';
    } else if (token === '-b' || token === '--cookie' || token === '-A' || token === '--user-agent') {
      value = readCurlOptionValue(tokens, i, token);
      i = value.index;
      appendConvenienceHeader(result.headers, token, value.value);
    } else if (token.indexOf('--cookie=') === 0) {
      result.headers.Cookie = token.substring('--cookie='.length);
    } else if (token.indexOf('--user-agent=') === 0) {
      result.headers['User-Agent'] = token.substring('--user-agent='.length);
    } else if (token === '--url') {
      result.url = tokens[++i] || '';
    } else if (token.indexOf('--url=') === 0) {
      result.url = token.substring('--url='.length);
    } else if (skipValueOptions[token]) {
      i += 1;
    } else if (token.charAt(0) !== '-' && !result.url) {
      result.url = token;
    }
  }

  if (!result.url) {
    throw new Error('未识别到请求 URL');
  }

  var normalizedUrl = normalizeImportedUrl(result.url);
  result.params = normalizedUrl.params;
  result.url = normalizedUrl.requestUrl;
  result.matchedEnvironmentId = normalizedUrl.environmentId;
  result.matchedBaseUrl = normalizedUrl.baseUrl;

  applyCurlBody(result, bodyParts, formParts, useQueryData, jsonByOption);
  if (!result.method) {
    result.method = result.bodyType === 'none' ? 'GET' : 'POST';
  }
  result.method = result.method.toUpperCase();
  return result;
}

function isCurlDataOption(token) {
  return token === '-d' ||
    token === '--data' ||
    token === '--data-raw' ||
    token === '--data-binary' ||
    token === '--data-ascii' ||
    token === '--data-urlencode' ||
    (token.indexOf('-d') === 0 && token.length > 2);
}

function readCurlOptionValue(tokens, index, token) {
  if (token.indexOf('-d') === 0 && token.length > 2) {
    return {value: token.substring(2), index: index};
  }
  return {value: tokens[index + 1] || '', index: index + 1};
}

function appendHeader(headers, headerLine) {
  var position = String(headerLine || '').indexOf(':');
  if (position <= 0) {
    return;
  }
  var key = headerLine.substring(0, position).trim();
  var value = headerLine.substring(position + 1).trim();
  if (key) {
    headers[key] = value;
  }
}

function ensureHeader(headers, key, value) {
  var exists = Object.keys(headers).some(function (item) {
    return item.toLowerCase() === key.toLowerCase();
  });
  if (!exists) {
    headers[key] = value;
  }
}

function appendConvenienceHeader(headers, option, value) {
  if (option === '-b' || option === '--cookie') {
    headers.Cookie = value;
  } else if (option === '-A' || option === '--user-agent') {
    headers['User-Agent'] = value;
  }
}

function normalizeImportedUrl(rawUrl) {
  var parsed;
  var params = {};
  var absoluteUrl = /^https?:\/\//i.test(rawUrl);
  try {
    parsed = new URL(rawUrl);
  } catch (err) {
    try {
      parsed = new URL(rawUrl, window.location.origin);
    } catch (innerErr) {
      throw new Error('URL 格式不正确');
    }
  }

  parsed.searchParams.forEach(function (value, key) {
    params[key] = value;
  });

  if (!absoluteUrl || !/^https?:$/i.test(parsed.protocol)) {
    return {
      requestUrl: parsed.pathname || rawUrl.split('?')[0],
      params: params,
      environmentId: null,
      baseUrl: ''
    };
  }

  var match = findEnvironmentByUrl(parsed.href);
  var requestUrl;
  if (match) {
    requestUrl = parsed.href.substring(match.baseUrl.length) || '/';
    requestUrl = requestUrl.split('?')[0] || '/';
  } else {
    requestUrl = parsed.origin + parsed.pathname;
  }
  return {
    requestUrl: requestUrl,
    params: params,
    environmentId: match ? match.id : null,
    baseUrl: match ? match.baseUrl : ''
  };
}

function findEnvironmentByUrl(url) {
  var environments = (interfaceOptions.environments || [])
    .filter(function (item) { return item.base_url; })
    .map(function (item) {
      return {
        id: item.id,
        baseUrl: String(item.base_url || '').replace(/\/+$/, '')
      };
    })
    .sort(function (left, right) {
      return right.baseUrl.length - left.baseUrl.length;
    });
  for (var i = 0; i < environments.length; i += 1) {
    var baseUrl = environments[i].baseUrl;
    if (url === baseUrl || url.indexOf(baseUrl + '/') === 0 || url.indexOf(baseUrl + '?') === 0) {
      return environments[i];
    }
  }
  return null;
}

function applyCurlBody(result, bodyParts, formParts, useQueryData, jsonByOption) {
  if (formParts.length) {
    result.bodyType = 'form-data';
    result.body = keyValueTextToObject(formParts.join('&'));
    return;
  }

  var bodyText = bodyParts.join('&');
  if (!bodyText) {
    result.bodyType = 'none';
    result.body = {};
    return;
  }

  if (useQueryData) {
    $.extend(result.params, keyValueTextToObject(bodyText));
    result.bodyType = 'none';
    result.body = {};
    return;
  }

  var parsedJson = tryParseJson(bodyText);
  if (jsonByOption || parsedJson.matched || headerContainsJson(result.headers)) {
    result.bodyType = 'json';
    result.body = parsedJson.matched ? parsedJson.value : bodyText;
    return;
  }

  if (looksLikeKeyValueText(bodyText)) {
    result.bodyType = 'x-www-form-urlencoded';
    result.body = keyValueTextToObject(bodyText);
    return;
  }

  result.bodyType = 'json';
  result.body = bodyText;
}

function tryParseJson(text) {
  try {
    return {matched: true, value: JSON.parse(text)};
  } catch (err) {
    return {matched: false, value: text};
  }
}

function headerContainsJson(headers) {
  return Object.keys(headers || {}).some(function (key) {
    return key.toLowerCase() === 'content-type' && String(headers[key]).toLowerCase().indexOf('json') >= 0;
  });
}

function looksLikeKeyValueText(text) {
  return /^[^=&]+=[\s\S]*/.test(text || '');
}

function keyValueTextToObject(text) {
  var data = {};
  String(text || '').split('&').forEach(function (part) {
    if (!part) {
      return;
    }
    var position = part.indexOf('=');
    var key = position >= 0 ? part.substring(0, position) : part;
    var value = position >= 0 ? part.substring(position + 1) : '';
    key = safeDecodeURIComponent(key.replace(/\+/g, ' '));
    value = safeDecodeURIComponent(value.replace(/\+/g, ' '));
    if (key) {
      data[key] = value;
    }
  });
  return data;
}

function safeDecodeURIComponent(value) {
  try {
    return decodeURIComponent(value);
  } catch (err) {
    return value;
  }
}

function applyCurlImport(parsed) {
  $('#interfaceType').val('http');
  $('#methodSelect').val(parsed.method || 'GET');
  $('#requestUrl').val(parsed.url || '');
  renderKvRows('#paramsTable', objectToRows(parsed.params || {}, true));
  renderHeaders(objectToRows(parsed.headers || {}, true));
  setBodyType(parsed.bodyType || 'none');
  if (parsed.bodyType === 'json') {
    $('#bodyJsonText').val(prettyJson(parsed.body));
  } else if (parsed.bodyType === 'form-data' || parsed.bodyType === 'x-www-form-urlencoded') {
    renderKvRows('#bodyTable', objectToRows(parsed.body || {}, true));
  }
  if (parsed.matchedEnvironmentId) {
    $('#environmentSelect').val(parsed.matchedEnvironmentId);
    rememberDebugEnvironment();
  }
  fillNameFromUrlIfEmpty(parsed.url);
  updateCounts();
  toggleByInterfaceType();
}

function fillNameFromUrlIfEmpty(url) {
  if ($('#interfaceName').val()) {
    return;
  }
  var path = String(url || '').split('?')[0].replace(/\/+$/, '');
  var last = path.split('/').pop();
  if (last) {
    $('#interfaceName').val(safeDecodeURIComponent(last));
  }
}

function importCurlToForm() {
  clearCurlImportMessage();
  try {
    var parsed = parseCurlCommand($('#curlImportText').val());
    applyCurlImport(parsed);
    showCurlImportInfo(parsed.matchedBaseUrl ? '已识别并匹配调试环境：' + parsed.matchedBaseUrl : '已识别 curl，并填充到接口表单。');
    setTimeout(function () {
      var modal = bootstrap.Modal.getInstance(document.getElementById('curlImportModal'));
      if (modal) {
        modal.hide();
      }
    }, 300);
  } catch (err) {
    showCurlImportError(err.message);
  }
}

function renderMethodOptions() {
  var methods = (interfaceOptions.methods && interfaceOptions.methods.length)
    ? interfaceOptions.methods
    : ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS'];
  methods = methods.filter(function (method) { return method !== 'WS'; });
  $('#methodSelect').html(methods.map(function (method) {
    return '<option value="' + method + '">' + method + '</option>';
  }).join(''));
}

function loadInterfaceIfNeeded() {
  var interfaceId = $('#interfaceId').val();
  if (!interfaceId) {
    addKvRow('#paramsTable');
    addPresetHeaders();
    setBodyType('none');
    updateCounts();
    return $.Deferred().resolve().promise();
  }
  return postJson('/api/interface-definition/detail', {interface_id: Number(interfaceId)}, function (resp) {
    fillInterface(resp.data || {});
  });
}

function fillInterface(item) {
  $('#projectSelect').val(item.project_id);
  renderModuleOptions(item.module_name || '');
  $('#interfaceName').val(item.name || '');
  $('#interfaceType').val(item.interface_type || 'http');
  $('#methodSelect').val(item.method || 'GET');
  $('#requestUrl').val(item.url || '');
  $('#interfaceActive').prop('checked', item.is_active !== false);
  setBodyType(item.body_type || 'none');
  renderKvRows('#paramsTable', objectToRows(item.params_template || {}, true));
  renderHeaders(objectToRows(item.headers_template || {}, true));
  fillBodyFromValue(item.body_template || {});
  updateCounts();
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
    '<td><input class="form-control kv-value" placeholder="Value，支持 {{变量}}" value="' + escapeHtml(row.value || '') + '"></td>' +
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
    return parseJsonText($('#bodyJsonText').val());
  }
  return {};
}

function beautifyBodyJson() {
  clearInterfaceError();
  try {
    $('#bodyJsonText').val(prettyJson(parseJsonText($('#bodyJsonText').val())));
  } catch (err) {
    showInterfaceError('JSON 格式错误：' + err.message);
  }
}

function collectPayload() {
  var module = selectedModule();
  return {
    project_id: Number($('#projectSelect').val()),
    module_id: module ? Number(module.id) : null,
    module_name: ($('#moduleInput').val() || '').trim(),
    name: $('#interfaceName').val(),
    interface_type: $('#interfaceType').val(),
    method: $('#methodSelect').val(),
    url: $('#requestUrl').val(),
    params_template: rowsToObject('#paramsTable'),
    headers_template: rowsToObject('#headersTable'),
    body_template: collectBody(),
    body_type: currentBodyType,
    timeout_seconds: Number($('#timeoutSeconds').val() || 30),
    description: '',
    is_active: $('#interfaceActive').is(':checked')
  };
}

function saveInterface() {
  clearInterfaceError();
  rememberDebugEnvironment();
  var payload;
  try {
    payload = collectPayload();
  } catch (err) {
    showInterfaceError('输入格式错误：' + err.message);
    return $.Deferred().reject().promise();
  }

  if (!payload.project_id) {
    showInterfaceError('请先选择项目');
    return $.Deferred().reject().promise();
  }
  if (!payload.name) {
    showInterfaceError('接口名称不能为空');
    return $.Deferred().reject().promise();
  }
  if (!payload.module_name) {
    showInterfaceError('请选择或输入所属模块');
    return $.Deferred().reject().promise();
  }

  var id = $('#interfaceId').val();
  if (id) {
    payload.interface_id = Number(id);
  }
  return $.ajax({
    url: id ? '/api/interface-definition/save' : '/api/interface-definition/create',
    method: 'POST',
    contentType: 'application/json',
    data: JSON.stringify(payload)
  }).done(function (resp) {
    $('#interfaceId').val(resp.data.id);
  }).fail(function (xhr) {
    showInterfaceError((xhr.responseJSON && xhr.responseJSON.message) || '保存失败');
  });
}

function debugInterface() {
  clearInterfaceError();
  var payload;
  try {
    payload = collectPayload();
  } catch (err) {
    showInterfaceError('输入格式错误：' + err.message);
    return;
  }
  if (!payload.project_id) {
    showInterfaceError('请先选择项目');
    return;
  }
  if (!Number($('#environmentSelect').val())) {
    showInterfaceError('请选择调试环境');
    return;
  }
  rememberDebugEnvironment();

  $('#debugStatus').removeClass().addClass('badge text-bg-secondary').text('发送中');
  $('#debugElapsed').text('- ms');
  $('#debugSize').text('- B');
  $('#responseEmpty').addClass('d-none');
  $('#debugBody').removeClass('d-none').text('请求发送中...');
  $.ajax({
    url: '/api/interface-definition/debug',
    method: 'POST',
    contentType: 'application/json',
    data: JSON.stringify($.extend({}, payload, {
      environment_id: Number($('#environmentSelect').val())
    }))
  }).done(function (resp) {
    renderDebug(resp.data || {});
  }).fail(function (xhr) {
    showInterfaceError((xhr.responseJSON && xhr.responseJSON.message) || '调试失败');
  });
}

function renderDebug(result) {
  var runner = result.runner || {};
  var response = runner.response || {};
  var responseContext = runner.response_context || {};
  var status = response.status_code || responseContext.status_code || '-';
  var elapsed = response.elapsed_ms || responseContext.elapsed_ms || '-';
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

function updateCounts() {
  $('#headersCount').text(Object.keys(rowsToObject('#headersTable')).length);
}

$('#addParamBtn').on('click', function () { addKvRow('#paramsTable'); });
$('#addBodyParamBtn').on('click', function () { addKvRow('#bodyTable'); });
$('#addHeaderBtn').on('click', function () { addKvRow('#headersTable'); updateCounts(); });
$('#addPresetHeadersBtn').on('click', addPresetHeaders);
$('.body-type').on('click', function () { setBodyType($(this).data('body-type')); });
$('#beautifyJsonBtn').on('click', beautifyBodyJson);
$('#applyCurlImportBtn').on('click', importCurlToForm);
$('#curlImportModal').on('shown.bs.modal', function () {
  clearCurlImportMessage();
  $('#curlImportText').trigger('focus');
});
$('#headersTable').on('input change', 'input', updateCounts);
$('#projectSelect').on('change', function () {
  renderModuleOptions('');
});
$('#environmentSelect').on('change', rememberDebugEnvironment);
$('#saveInterfaceBtn').on('click', function () {
  saveInterface().done(function () { window.location.href = '/interfaces/'; });
});
$('#debugBtn').on('click', debugInterface);
$(document).on('click', '.remove-row', function () {
  var row = $(this).closest('tr')[0];
  AppCombobox.destroyWithin(row);
  $(row).remove();
  updateCounts();
});

$.when(loadOptions()).done(loadInterfaceIfNeeded);
