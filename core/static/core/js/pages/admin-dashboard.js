(function () {
  // Period filter: reload the dashboard as soon as a new period is picked.
  var rangeSelect = document.querySelector('[data-auto-submit]');
  if (rangeSelect && rangeSelect.form) {
    rangeSelect.addEventListener('change', function () { rangeSelect.form.submit(); });
  }

  if (typeof Chart === 'undefined') return;
  var dataEl = document.getElementById('dashboardChartData');
  var canvas = document.getElementById('chartDashboardTrend');
  if (!dataEl || !canvas) return;
  var trend = JSON.parse(dataEl.textContent).trend;

  Chart.defaults.font.family = 'system-ui, -apple-system, "Segoe UI", sans-serif';
  Chart.defaults.font.size = 12;
  Chart.defaults.color = '#64748b';

  new Chart(canvas, {
    type: 'bar',
    data: {
      labels: trend.labels,
      datasets: [
        { label: 'Submitted', data: trend.submitted, backgroundColor: '#6ee7b7', borderRadius: 4, maxBarThickness: 18 },
        { label: 'Approved', data: trend.approved, backgroundColor: '#047857', borderRadius: 4, maxBarThickness: 18 }
      ]
    },
    options: {
      maintainAspectRatio: false,
      animation: { duration: 300 },
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#ffffff',
          titleColor: '#0f172a',
          bodyColor: '#475569',
          borderColor: 'rgba(15,23,42,0.10)',
          borderWidth: 1,
          padding: 10,
          boxPadding: 4,
          usePointStyle: true
        }
      },
      scales: {
        x: {
          grid: { display: false },
          border: { color: '#cbd5e1' },
          ticks: {
            maxRotation: 0,
            autoSkip: true,
            callback: function (value) { return this.getLabelForValue(value).split(' ')[0]; }
          }
        },
        y: {
          beginAtZero: true,
          grid: { color: '#eef2f6' },
          border: { display: false },
          ticks: { precision: 0 }
        }
      }
    }
  });
})();
