var dashboardState = {projectId: null, days: 14, trend: []};
var dashboardStatusLabels = {pass: '通过', fail: '失败', error: '错误', skipped: '跳过'};
var dashboardStatusColors = {pass: '#22a06b', fail: '#e5a000', error: '#dc3545', skipped: '#9ca3af'};

function initializeDashboardState() {
  var params = new URLSearchParams(window.location.search);
  var projectId = Number(params.get('project_id'));
  var days = Number(params.get('days'));
  dashboardState.projectId = projectId > 0 ? projectId : null;
  dashboardState.days = [7, 14, 30].indexOf(days) >= 0 ? days : 14;
  $('#dashboardDaysFilter').val(String(dashboardState.days));
}

function syncDashboardUrl() {
  var params = new URLSearchParams(window.location.search);
  if (dashboardState.projectId) {
    params.set('project_id', dashboardState.projectId);
  } else {
    params.delete('project_id');
  }
  params.set('days', dashboardState.days);
  var query = params.toString();
  window.history.replaceState({}, '', window.location.pathname + (query ? '?' + query : ''));
}

function loadDashboardStatistics() {
  $('#dashboardError').addClass('d-none').text('');
  return $.ajax({
    url: '/api/dashboard/statistics',
    method: 'POST',
    contentType: 'application/json',
    data: JSON.stringify({project_id: dashboardState.projectId, days: dashboardState.days})
  }).done(function (response) {
    renderDashboardStatistics(response.data || {});
  }).fail(function (xhr) {
    var message = xhr.responseJSON && xhr.responseJSON.message;
    $('#dashboardError').removeClass('d-none').text(message || '仪表盘数据加载失败');
  });
}

function renderDashboardStatistics(data) {
  renderDashboardProjectOptions(data.projects || []);
  renderDashboardMetrics(data.metrics || {});
  dashboardState.trend = data.trend || [];
  drawDashboardTrend(dashboardState.trend);
  renderDashboardDistribution(data.distribution || {});
  $('.statistics-period-note').text('仅统计定时任务 · 最近 ' + dashboardState.days + ' 天');
}

function renderDashboardProjectOptions(projects) {
  var options = '<option value="">全部项目</option>' + projects.map(function (project) {
    return '<option value="' + project.id + '">' + escapeDashboardHtml(project.name) + '</option>';
  }).join('');
  $('#dashboardProjectFilter').html(options).val(dashboardState.projectId ? String(dashboardState.projectId) : '');
}

function renderDashboardMetrics(metrics) {
  $('#projectMetric').text(metrics.project_count || 0);
  $('#interfaceMetric').text(metrics.interface_count || 0);
  $('#caseMetric').text(metrics.case_count || 0);
  $('#suiteMetric').text(metrics.suite_count || 0);
  $('#reportMetric').text(metrics.report_count || 0);
}

function renderDashboardDistribution(distribution) {
  var total = Number(distribution.total || 0);
  var passCount = Number(distribution.pass || 0);
  var failCount = Number(distribution.fail || 0);
  var errorCount = Number(distribution.error || 0);
  var skippedCount = Number(distribution.skipped || 0);
  var passStop = total ? passCount * 100 / total : 0;
  var failStop = passStop + (total ? failCount * 100 / total : 0);
  var errorStop = failStop + (total ? errorCount * 100 / total : 0);
  var $donut = $('#resultDonut');

  $donut
    .toggleClass('is-empty', total === 0)
    .css('--pass-stop', passStop.toFixed(2) + '%')
    .css('--fail-stop', failStop.toFixed(2) + '%')
    .css('--error-stop', errorStop.toFixed(2) + '%')
    .attr('aria-label', total
      ? '共执行 ' + total + ' 个用例步骤，通过率 ' + Number(distribution.pass_rate || 0).toFixed(1) + '%'
      : '暂无定时任务执行数据');
  $('#passRate').text(Number(distribution.pass_rate || 0).toFixed(1) + '%');
  $('#passCount').text(passCount);
  $('#failCount').text(failCount);
  $('#errorCount').text(errorCount);
  $('#skippedCount').text(skippedCount);
}

function drawDashboardTrend(items) {
  var svg = document.getElementById('trendChart');
  var wrap = document.getElementById('trendChartWrap');
  if (!svg || !wrap) return;

  var containerWidth = Math.round(wrap.getBoundingClientRect().width || 640);
  var rotatedLabels = items.length > 7;
  var minimumSlotWidth = rotatedLabels ? 32 : 44;
  var minimumChartWidth = items.length * minimumSlotWidth + 52;
  var width = Math.max(320, containerWidth, minimumChartWidth);
  var height = rotatedLabels ? 310 : 280;
  var margin = {top: 14, right: 10, bottom: rotatedLabels ? 72 : 42, left: 42};
  var plotWidth = width - margin.left - margin.right;
  var plotHeight = height - margin.top - margin.bottom;
  var totals = items.map(function (item) {
    return Number(item.pass || 0) + Number(item.fail || 0) + Number(item.error || 0) + Number(item.skipped || 0);
  });
  var maxTotal = Math.max.apply(null, totals.concat([5]));
  var tickMaximum = Math.ceil(maxTotal / 5) * 5;
  var slotWidth = items.length ? plotWidth / items.length : plotWidth;
  var barWidth = Math.max(4, Math.min(24, slotWidth * 0.58));
  var parts = [
    '<title id="trendChartTitle">定时任务用例执行趋势</title>',
    '<desc id="trendChartDescription">按日期堆叠展示通过、失败、错误和跳过的用例执行数量。</desc>'
  ];

  for (var tick = 0; tick <= 4; tick += 1) {
    var tickValue = tickMaximum / 4 * tick;
    var tickY = margin.top + plotHeight - tickValue / tickMaximum * plotHeight;
    parts.push('<line class="dashboard-trend-grid" x1="' + margin.left + '" y1="' + tickY +
      '" x2="' + (width - margin.right) + '" y2="' + tickY + '"></line>');
    parts.push('<text class="dashboard-trend-label" x="' + (margin.left - 8) + '" y="' + (tickY + 4) +
      '" text-anchor="end">' + Math.round(tickValue) + '</text>');
  }

  items.forEach(function (item, index) {
    var x = margin.left + index * slotWidth + (slotWidth - barWidth) / 2;
    var accumulated = 0;
    ['pass', 'fail', 'error', 'skipped'].forEach(function (status) {
      var value = Number(item[status] || 0);
      if (!value) return;
      var segmentHeight = value / tickMaximum * plotHeight;
      var y = margin.top + plotHeight - (accumulated + value) / tickMaximum * plotHeight;
      var tooltip = formatDashboardDate(item.date) + ' · ' + dashboardStatusLabels[status] + ' ' + value;
      parts.push('<rect x="' + x.toFixed(1) + '" y="' + y.toFixed(1) + '" width="' + barWidth.toFixed(1) +
        '" height="' + Math.max(1, segmentHeight).toFixed(1) + '" rx="2" fill="' + dashboardStatusColors[status] +
        '"><title>' + escapeDashboardHtml(tooltip) + '</title></rect>');
      accumulated += value;
    });
    var labelX = x + barWidth / 2;
    var labelY = margin.top + plotHeight + 16;
    var labelTransform = rotatedLabels
      ? ' transform="rotate(-45 ' + labelX.toFixed(1) + ' ' + labelY.toFixed(1) + ')" text-anchor="end"'
      : ' text-anchor="middle"';
    parts.push('<text class="dashboard-trend-label" x="' + labelX.toFixed(1) +
      '" y="' + labelY.toFixed(1) + '"' + labelTransform + '>' +
      escapeDashboardHtml(formatDashboardDate(item.date)) + '</text>');
  });

  if (!totals.some(function (total) { return total > 0; })) {
    parts.push('<text class="dashboard-trend-label" x="' + (margin.left + plotWidth / 2) +
      '" y="' + (margin.top + plotHeight / 2) + '" text-anchor="middle">暂无定时任务执行数据</text>');
  }
  svg.setAttribute('viewBox', '0 0 ' + width + ' ' + height);
  svg.style.width = width + 'px';
  svg.innerHTML = parts.join('');
}

function formatDashboardDate(value) {
  var parts = String(value || '').split('-');
  return parts.length === 3 ? parts[1] + '-' + parts[2] : String(value || '');
}

function escapeDashboardHtml(value) {
  return $('<div>').text(value === null || value === undefined ? '' : String(value)).html();
}

$('#dashboardProjectFilter').on('change', function () {
  dashboardState.projectId = Number($(this).val()) || null;
  syncDashboardUrl();
  loadDashboardStatistics();
});

$('#dashboardDaysFilter').on('change', function () {
  dashboardState.days = Number($(this).val()) || 14;
  syncDashboardUrl();
  loadDashboardStatistics();
});

if (window.ResizeObserver) {
  new ResizeObserver(function () { drawDashboardTrend(dashboardState.trend); })
    .observe(document.getElementById('trendChartWrap'));
} else {
  $(window).on('resize', function () { drawDashboardTrend(dashboardState.trend); });
}

initializeDashboardState();
loadDashboardStatistics();
