(function () {
  const menuEl = document.getElementById('menu-engineering-data');
  if (menuEl) {
    const md = JSON.parse(menuEl.textContent);
    const colors = { Star: '#16a34a', Plowhorse: '#2563eb', Puzzle: '#f59e0b', Dog: '#dc2626' };
    const matrix = document.getElementById('menuMatrixChart');
    if (matrix) {
      const points = (md.rows || []).map(r => ({
        x: r.quantity_sold,
        y: r.contribution_margin,
        item_name: r.item_name,
        category: r.category,
        selling_price: r.selling_price,
        classification: r.classification,
      }));
      new Chart(matrix, {
        type: 'scatter',
        data: {
          datasets: [
            {
              label: 'Menu Items',
              data: points,
              pointRadius: 7,
              pointBackgroundColor: points.map(p => colors[p.classification] || '#6b7280')
            },
            {
              label: 'Avg Popularity',
              type: 'line',
              data: [{x: md.avg_popularity, y: 0}, {x: md.avg_popularity, y: Math.max(...points.map(p => p.y), md.avg_profitability + 5)}],
              borderColor: '#6b7280',
              borderDash: [5,5],
              pointRadius: 0
            },
            {
              label: 'Avg Profitability',
              type: 'line',
              data: [{x: 0, y: md.avg_profitability}, {x: Math.max(...points.map(p => p.x), md.avg_popularity + 5), y: md.avg_profitability}],
              borderColor: '#6b7280',
              borderDash: [5,5],
              pointRadius: 0
            }
          ]
        },
        options: {
          plugins: {
            legend: {display: true},
            tooltip: {
              callbacks: {
                label: (ctx) => {
                  const p = ctx.raw;
                  return `${p.item_name} | ${p.category} | Qty ${p.x} | Margin RM${p.y} | ${p.classification}`;
                }
              }
            }
          },
          scales: {
            x: {title: {display: true, text: 'Popularity (Quantity Sold)'}},
            y: {title: {display: true, text: 'Profitability (RM Contribution Margin)'}}
          }
        }
      });
    }
  }

  const dataEl = document.getElementById('chart-data');
  if (!dataEl) return;
  const data = JSON.parse(dataEl.textContent);

  const mkLine = (id, labels, series, label, color) => {
    const el = document.getElementById(id);
    if (!el) return;
    new Chart(el, {
      type: 'line',
      data: { labels, datasets: [{ label, data: series, borderColor: color, fill: false }] },
      options: { responsive: true, maintainAspectRatio: false }
    });
  };

  mkLine('revenueChart', data.revenue_labels || [], data.revenue_values || [], 'Revenue', '#0d6efd');
  mkLine('cashChart', data.revenue_labels || [], data.cash_values || [], 'Cash Flow', '#198754');
  mkLine('forecastRevenue', data.forecast_labels || [], data.forecast_revenue || [], 'Forecast Revenue', '#6f42c1');
  mkLine('forecastCash', data.forecast_labels || [], data.forecast_cash || [], 'Forecast Cash Flow', '#fd7e14');

  const pieEl = document.getElementById('sentimentPie');
  if (pieEl) {
    new Chart(pieEl, {
      type: 'pie',
      data: {
        labels: ['Positive', 'Neutral', 'Negative'],
        datasets: [{ data: [data.sentiment_counts.positive || 0, data.sentiment_counts.neutral || 0, data.sentiment_counts.negative || 0] }]
      }
    });
  }

  const sEl = document.getElementById('sentimentSales');
  if (sEl) {
    new Chart(sEl, {
      type: 'line',
      data: {
        labels: data.sentiment_vs_sales_labels || [],
        datasets: [
          { label: 'Revenue', data: data.sentiment_vs_sales_revenue || [], borderColor: '#0d6efd', yAxisID: 'y' },
          { label: 'Sentiment Index', data: data.sentiment_vs_sales_sentiment || [], borderColor: '#dc3545', yAxisID: 'y1' }
        ]
      },
      options: {
        scales: { y: { type: 'linear', position: 'left' }, y1: { type: 'linear', position: 'right' } }
      }
    });
  }
})();
