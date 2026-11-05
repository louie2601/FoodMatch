(function () {
  if (typeof Chart === 'undefined') return;
  var data = JSON.parse(document.getElementById('reportsChartData').textContent);

  var INK = { primary: '#0b0b0b', secondary: '#52514e', muted: '#898781' };
  var GRID = '#e1e0d9';
  var AXIS = '#c3c2b7';
  var SURFACE = '#ffffff';
  var SERIES = '#059669';
  var STATUS = { good: '#0ca30c', warning: '#fab219', critical: '#d03b3b' };
  var STATUS_BY_KEY = {
    approved: STATUS.good, pending: STATUS.warning, rejected: STATUS.critical,
    low: STATUS.good, moderate: STATUS.warning, high: STATUS.critical
  };

  Chart.defaults.font.family = 'system-ui, -apple-system, "Segoe UI", sans-serif';
  Chart.defaults.font.size = 12;
  Chart.defaults.color = INK.secondary;
  Chart.defaults.maintainAspectRatio = false;
  Chart.defaults.animation = { duration: 300 };

  var tooltip = {
    backgroundColor: SURFACE,
    titleColor: INK.primary,
    bodyColor: INK.secondary,
    borderColor: 'rgba(11,11,11,0.10)',
    borderWidth: 1,
    padding: 10,
    boxPadding: 4,
    usePointStyle: true,
    titleFont: { weight: '600' }
  };

  // Selective direct labels: only charts that opt in get a value at the bar end.
  var valueLabels = {
    id: 'valueLabels',
    afterDatasetsDraw: function (chart, args, opts) {
      if (!opts || !opts.display) return;
      var ctx = chart.ctx;
      var horizontal = chart.options.indexAxis === 'y';
      ctx.save();
      ctx.font = '600 12px ' + Chart.defaults.font.family;
      ctx.fillStyle = INK.primary;
      chart.data.datasets.forEach(function (dataset, di) {
        chart.getDatasetMeta(di).data.forEach(function (bar, i) {
          var value = dataset.data[i];
          if (!value) return;
          if (horizontal) {
            ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
            ctx.fillText(value, bar.x + 6, bar.y);
          } else {
            ctx.textAlign = 'center'; ctx.textBaseline = 'bottom';
            ctx.fillText(value, bar.x, bar.y - 4);
          }
        });
      });
      ctx.restore();
    }
  };

  function valueAxis(extra) {
    return Object.assign({
      beginAtZero: true,
      grace: '12%',
      border: { display: false },
      grid: { color: GRID, lineWidth: 1, drawTicks: false },
      ticks: { precision: 0, color: INK.muted, padding: 8 }
    }, extra || {});
  }
  function categoryAxis(extra) {
    return Object.assign({
      border: { color: AXIS },
      grid: { display: false },
      ticks: { color: INK.secondary, padding: 6 }
    }, extra || {});
  }
  function barStyle(colors) {
    return {
      backgroundColor: colors,
      hoverBackgroundColor: colors,
      borderColor: SURFACE,
      borderWidth: 2,
      borderSkipped: 'start',
      borderRadius: 4,
      maxBarThickness: 40
    };
  }

  // 1) Submissions per month - stacked by status, legend + index tooltip.
  var monthCanvas = document.getElementById('chartSubmissionsByMonth');
  if (monthCanvas) {
    var series = data.submissionsByMonth.series;
    new Chart(monthCanvas, {
      type: 'bar',
      data: {
        labels: data.submissionsByMonth.labels,
        datasets: series.map(function (s) {
          var color = STATUS_BY_KEY[s.key];
          return Object.assign({ label: s.label, data: s.values }, barStyle(color), {
            // Round only the top-most non-zero segment of each stack.
            borderRadius: function (ctx) {
              var i = ctx.dataIndex, top = -1;
              series.forEach(function (other, di) { if (other.values[i] > 0) top = di; });
              return ctx.datasetIndex === top ? { topLeft: 4, topRight: 4 } : 0;
            }
          });
        })
      },
      options: {
        interaction: { mode: 'index', intersect: false },
        scales: {
          x: categoryAxis({ stacked: true }),
          y: valueAxis({ stacked: true })
        },
        plugins: {
          legend: {
            position: 'top', align: 'start',
            labels: { usePointStyle: true, pointStyle: 'rectRounded', boxWidth: 10, boxHeight: 10, color: INK.secondary, padding: 16 }
          },
          tooltip: Object.assign({}, tooltip, {
            itemSort: function (a, b) { return a.datasetIndex - b.datasetIndex; },
            footer: function (items) {
              var total = items.reduce(function (sum, item) { return sum + item.parsed.y; }, 0);
              return 'Total: ' + total;
            }
          })
        }
      }
    });
  }

  // 2) Similarity levels - status colors, the level name on the axis carries meaning.
  var levelCanvas = document.getElementById('chartSimilarityLevels');
  if (levelCanvas) {
    var levels = data.similarityLevels;
    new Chart(levelCanvas, {
      type: 'bar',
      data: {
        labels: levels.map(function (l) { return l.label; }),
        datasets: [Object.assign({ label: 'Checks', data: levels.map(function (l) { return l.count; }) },
          barStyle(levels.map(function (l) { return STATUS_BY_KEY[l.key]; })))]
      },
      options: {
        scales: { x: categoryAxis(), y: valueAxis() },
        plugins: { legend: { display: false }, tooltip: tooltip, valueLabels: { display: true } }
      },
      plugins: [valueLabels]
    });
  }

  // 3) Submissions by college - single series, horizontal.
  var collegeCanvas = document.getElementById('chartSubmissionsByCollege');
  if (collegeCanvas) {
    var colleges = data.submissionsByCollege;
    new Chart(collegeCanvas, {
      type: 'bar',
      data: {
        labels: colleges.map(function (c) { return c.label; }),
        datasets: [Object.assign({ label: 'Submissions', data: colleges.map(function (c) { return c.count; }) }, barStyle(SERIES))]
      },
      options: {
        indexAxis: 'y',
        scales: { x: valueAxis(), y: categoryAxis() },
        plugins: {
          legend: { display: false },
          tooltip: Object.assign({}, tooltip, {
            callbacks: { title: function (items) { return colleges[items[0].dataIndex].full_label; } }
          }),
          valueLabels: { display: true }
        }
      },
      plugins: [valueLabels]
    });
  }

  // 4) Research by food category - single series, horizontal, ranked.
  var categoryCanvas = document.getElementById('chartResearchByCategory');
  if (categoryCanvas) {
    var categories = data.researchByCategory;
    new Chart(categoryCanvas, {
      type: 'bar',
      data: {
        labels: categories.map(function (c) { return c.label; }),
        datasets: [Object.assign({ label: 'Studies', data: categories.map(function (c) { return c.count; }) }, barStyle(SERIES), { maxBarThickness: 22 })]
      },
      options: {
        indexAxis: 'y',
        scales: { x: valueAxis(), y: categoryAxis() },
        plugins: { legend: { display: false }, tooltip: tooltip }
      }
    });
  }

  // 5) Repository by published year - single series columns.
  var yearCanvas = document.getElementById('chartRepositoryByYear');
  if (yearCanvas) {
    var years = data.repositoryByYear;
    new Chart(yearCanvas, {
      type: 'bar',
      data: {
        labels: years.map(function (y) { return y.label; }),
        datasets: [Object.assign({ label: 'Studies', data: years.map(function (y) { return y.count; }) }, barStyle(SERIES))]
      },
      options: {
        scales: { x: categoryAxis(), y: valueAxis() },
        plugins: { legend: { display: false }, tooltip: tooltip }
      }
    });
  }
})();
