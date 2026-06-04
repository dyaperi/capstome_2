(function () {
  const storageKey = 'fnb.sidebar.expanded';
  const sidebarToggles = document.querySelectorAll('[data-sidebar-toggle]');

  const getExpandedItems = () => {
    try {
      return JSON.parse(localStorage.getItem(storageKey) || '[]');
    } catch (err) {
      return [];
    }
  };

  const setExpandedItems = (items) => {
    try {
      localStorage.setItem(storageKey, JSON.stringify(items));
    } catch (err) {
      // Ignore storage errors so navigation never breaks.
    }
  };

  if (sidebarToggles.length) {
    const expandedItems = new Set(getExpandedItems());

    sidebarToggles.forEach((toggle) => {
      const targetId = toggle.getAttribute('data-sidebar-toggle');
      const target = document.getElementById(targetId);
      if (!target) return;

      const shouldOpen = toggle.classList.contains('active') || expandedItems.has(targetId);
      target.classList.toggle('show', shouldOpen);
      toggle.classList.toggle('expanded', shouldOpen);
      toggle.setAttribute('aria-expanded', shouldOpen ? 'true' : 'false');

      toggle.addEventListener('click', () => {
        const isOpen = target.classList.toggle('show');
        toggle.classList.toggle('expanded', isOpen);
        toggle.setAttribute('aria-expanded', isOpen ? 'true' : 'false');

        const saved = new Set(getExpandedItems());
        if (isOpen) {
          saved.add(targetId);
        } else {
          saved.delete(targetId);
        }
        setExpandedItems(Array.from(saved));
      });
    });
  }

  const closeClientActionMenus = () => {
    document.querySelectorAll('.client-action-menu.show').forEach((menu) => {
      menu.classList.remove('show');
      const trigger = menu.parentElement && menu.parentElement.querySelector('[data-client-actions]');
      if (trigger) trigger.setAttribute('aria-expanded', 'false');
    });
  };

  document.querySelectorAll('[data-client-actions]').forEach((trigger) => {
    trigger.setAttribute('aria-expanded', 'false');
    trigger.addEventListener('click', (event) => {
      event.stopPropagation();
      const menu = trigger.parentElement && trigger.parentElement.querySelector('.client-action-menu');
      if (!menu) return;
      const isOpen = menu.classList.contains('show');
      closeClientActionMenus();
      menu.classList.toggle('show', !isOpen);
      trigger.setAttribute('aria-expanded', !isOpen ? 'true' : 'false');
    });
  });

  document.addEventListener('click', closeClientActionMenus);
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeClientActionMenus();
  });

  const closeModal = (modal) => {
    if (!modal) return;
    modal.classList.remove('show');
    modal.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('modal-open');
  };

  document.querySelectorAll('[data-modal-open]').forEach((button) => {
    button.addEventListener('click', () => {
      const modal = document.getElementById(button.getAttribute('data-modal-open'));
      if (!modal) return;
      modal.classList.add('show');
      modal.setAttribute('aria-hidden', 'false');
      document.body.classList.add('modal-open');
      const firstInput = modal.querySelector('input, select, button');
      if (firstInput) firstInput.focus();
    });
  });

  document.querySelectorAll('[data-modal-close]').forEach((button) => {
    button.addEventListener('click', () => {
      closeModal(button.closest('.client-modal'));
    });
  });

  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    document.querySelectorAll('.client-modal.show').forEach(closeModal);
  });

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
          responsive: true,
          maintainAspectRatio: false,
          devicePixelRatio: window.devicePixelRatio || 1,
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

  const salesMenuEl = document.getElementById('sales-menu-data');
  if (salesMenuEl) {
    const menuSnapshots = JSON.parse(salesMenuEl.textContent || '[]');
    const menuById = new Map(menuSnapshots.map(item => [String(item.id), item]));
    const menuSelect = document.getElementById('menuItemSelect');
    const unitPriceDisplay = document.getElementById('unitPriceDisplay');
    const unitCostDisplay = document.getElementById('unitCostDisplay');

    const updateSalesSnapshotFields = () => {
      if (!menuSelect || !unitPriceDisplay || !unitCostDisplay) return;
      const snapshot = menuById.get(menuSelect.value);
      unitPriceDisplay.value = snapshot ? Number(snapshot.unit_price || 0).toFixed(2) : '';
      unitCostDisplay.value = snapshot ? Number(snapshot.unit_cost || 0).toFixed(2) : '';
    };

    updateSalesSnapshotFields();
    if (menuSelect) {
      menuSelect.addEventListener('change', updateSalesSnapshotFields);
    }
  }

  const inventoryChartDataEl = document.getElementById('inventory-chart-data');
  const inventoryCategoryEl = document.getElementById('inventoryCategoryChart');
  if (inventoryChartDataEl && inventoryCategoryEl) {
    const categoryRows = JSON.parse(inventoryChartDataEl.textContent || '[]');
    const inventoryColors = ['#0b5d46', '#0f766e', '#1f7a5b', '#0d5b46', '#265f4b', '#3a7a5d'];
    new Chart(inventoryCategoryEl, {
      type: 'bar',
      data: {
        labels: categoryRows.map((row) => row.label),
        datasets: [{
          data: categoryRows.map((row) => row.value),
          backgroundColor: categoryRows.map((_, index) => inventoryColors[index % inventoryColors.length]),
          borderRadius: 8,
          borderSkipped: false,
          maxBarThickness: 48
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        devicePixelRatio: window.devicePixelRatio || 1,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (ctx) => `${ctx.label}: ${ctx.raw} item${ctx.raw === 1 ? '' : 's'}`
            }
          }
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: {
              color: '#6b7280',
              font: { size: 11, weight: '600' }
            }
          },
          y: {
            beginAtZero: true,
            ticks: {
              precision: 0,
              stepSize: 1,
              color: '#94a3b8'
            },
            grid: { color: 'rgba(148, 163, 184, .18)' }
          }
        }
      }
    });
  }

  const dataEl = document.getElementById('chart-data');
  if (!dataEl) return;
  const data = JSON.parse(dataEl.textContent);
  const money = new Intl.NumberFormat('en-MY', { style: 'currency', currency: 'MYR' });
  const compactMoney = new Intl.NumberFormat('en-MY', {
    style: 'currency',
    currency: 'MYR',
    notation: 'compact',
    maximumFractionDigits: 1
  });
  const shortDate = new Intl.DateTimeFormat('en-MY', { day: 'numeric', month: 'short' });
  const longDate = new Intl.DateTimeFormat('en-MY', { day: 'numeric', month: 'short', year: 'numeric' });

  const formatChartDate = (label, formatter = shortDate) => {
    if (typeof label !== 'string') return label;
    const date = new Date(`${label}T00:00:00`);
    if (Number.isNaN(date.getTime())) return label;
    return formatter.format(date);
  };

  const mkLine = (id, labels, series, label, color, options = {}) => {
    const el = document.getElementById(id);
    if (!el) return;
    const pointColor = options.pointColor || color;
    const maxXLabels = options.maxXLabels || 8;
    const labelStep = Math.max(1, Math.ceil((labels || []).length / maxXLabels));
    const pointRadius = labels.length > 45 ? 0 : labels.length > 24 ? 2.5 : 3.5;

    new Chart(el, {
      type: 'line',
      data: {
        labels,
        datasets: [
          {
            label,
            data: series,
            borderColor: color,
            backgroundColor: color,
            tension: 0.36,
            borderWidth: 3,
            borderCapStyle: 'round',
            borderJoinStyle: 'round',
            pointRadius,
            pointHoverRadius: 6,
            pointBorderWidth: 2,
            pointBackgroundColor: '#ffffff',
            pointBorderColor: pointColor,
            hitRadius: 10,
            fill: false
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        devicePixelRatio: window.devicePixelRatio || 1,
        interaction: {
          mode: 'index',
          intersect: false
        },
        layout: {
          padding: {
            top: 8,
            right: 14,
            bottom: 0,
            left: 4
          }
        },
        plugins: {
          legend: {
            display: true,
            position: 'bottom',
            align: 'center',
            labels: {
              boxWidth: 10,
              boxHeight: 10,
              usePointStyle: true,
              padding: 18,
              color: '#334155',
              font: { weight: '700' }
            }
          },
          tooltip: {
            mode: 'index',
            intersect: false,
            backgroundColor: '#0f172a',
            titleColor: '#f8fafc',
            bodyColor: '#e2e8f0',
            borderColor: 'rgba(148, 163, 184, .35)',
            borderWidth: 1,
            cornerRadius: 8,
            displayColors: true,
            padding: 12,
            callbacks: {
              title: (items) => {
                const item = items && items[0];
                return item ? formatChartDate(item.label, longDate) : '';
              },
              label: (ctx) => `${ctx.dataset.label}: ${money.format(Number(ctx.raw || 0))}`
            }
          }
        },
        scales: {
          x: {
            grid: { display: false },
            border: { color: 'rgba(148, 163, 184, .32)' },
            title: {
              display: true,
              text: options.xTitle || 'Date',
              color: '#475569',
              font: { weight: '700' }
            },
            ticks: {
              color: '#64748b',
              maxRotation: 0,
              autoSkip: false,
              padding: 8,
              font: { weight: '600' },
              callback: (value, index) => {
                const isEndpoint = index === 0 || index === labels.length - 1;
                if (!isEndpoint && index % labelStep !== 0) return '';
                return formatChartDate(labels[index]);
              }
            }
          },
          y: {
            beginAtZero: true,
            grid: {
              color: 'rgba(148, 163, 184, .22)',
              drawBorder: false
            },
            border: { display: false },
            title: {
              display: true,
              text: options.yTitle || 'Amount (RM)',
              color: '#475569',
              font: { weight: '700' }
            },
            ticks: {
              color: '#64748b',
              padding: 8,
              callback: (value) => compactMoney.format(Number(value))
            }
          }
        }
      }
    });
  };

  const monthlyTrendEl = document.getElementById('monthlyRevenueTrendChart');
  if (monthlyTrendEl) {
    const trend = data.monthly_revenue_trend || {};
    new Chart(monthlyTrendEl, {
      type: 'line',
      data: {
        labels: trend.labels || [],
        datasets: [
          {
            label: 'Gross Revenue',
            data: trend.gross_revenue || [],
            borderColor: '#0d6efd',
            backgroundColor: '#0d6efd',
            tension: 0.36,
            borderWidth: 3,
            pointRadius: 4,
            pointHoverRadius: 6,
            pointBorderWidth: 2,
            pointBackgroundColor: '#ffffff',
            fill: false
          },
          {
            label: 'Net Income',
            data: trend.net_income || [],
            borderColor: '#198754',
            backgroundColor: '#198754',
            tension: 0.36,
            borderWidth: 3,
            pointRadius: 4,
            pointHoverRadius: 6,
            pointBorderWidth: 2,
            pointBackgroundColor: '#ffffff',
            fill: false
          },
          {
            label: 'Total Expenses',
            data: trend.total_expenses || [],
            borderColor: '#dc3545',
            backgroundColor: '#dc3545',
            tension: 0.36,
            borderWidth: 3,
            pointRadius: 4,
            pointHoverRadius: 6,
            pointBorderWidth: 2,
            pointBackgroundColor: '#ffffff',
            fill: false
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        devicePixelRatio: window.devicePixelRatio || 1,
        interaction: {
          mode: 'index',
          intersect: false
        },
        plugins: {
          legend: {
            display: true,
            position: 'bottom',
            labels: {
              boxWidth: 10,
              boxHeight: 10,
              usePointStyle: true,
              padding: 18
            }
          },
          tooltip: {
            mode: 'index',
            intersect: false,
            callbacks: {
              label: (ctx) => `${ctx.dataset.label}: ${money.format(Number(ctx.raw || 0))}`
            }
          }
        },
        scales: {
          x: {
            grid: { color: 'rgba(148, 163, 184, .2)' },
            title: { display: true, text: 'Month' },
            ticks: { color: '#64748b' }
          },
          y: {
            beginAtZero: true,
            grid: { color: 'rgba(148, 163, 184, .24)' },
            title: { display: true, text: 'Amount (RM)' },
            ticks: {
              color: '#64748b',
              callback: (value) => money.format(Number(value))
            }
          }
        }
      }
    });
  }

  const salesRoiEl = document.getElementById('salesRoiChart');
  if (salesRoiEl) {
    const salesRoi = data.monthly_sales_roi_graph || {};
    new Chart(salesRoiEl, {
      type: 'bar',
      data: {
        labels: salesRoi.labels || [],
        datasets: [
          {
            type: 'bar',
            label: 'Sales',
            data: salesRoi.sales || [],
            yAxisID: 'sales',
            backgroundColor: '#e3423d',
            borderColor: '#e3423d',
            borderWidth: 1,
            borderRadius: 2,
            maxBarThickness: 42,
            categoryPercentage: 0.62,
            barPercentage: 0.82
          },
          {
            type: 'line',
            label: 'ROI',
            data: salesRoi.roi || [],
            yAxisID: 'roi',
            borderColor: '#264552',
            backgroundColor: '#264552',
            borderWidth: 3,
            pointRadius: 4,
            pointHoverRadius: 6,
            pointBackgroundColor: '#ffffff',
            pointBorderColor: '#264552',
            pointBorderWidth: 2,
            tension: 0.34,
            fill: false
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        devicePixelRatio: window.devicePixelRatio || 1,
        interaction: {
          mode: 'index',
          intersect: false
        },
        plugins: {
          legend: {
            display: true,
            position: 'bottom',
            labels: {
              boxWidth: 28,
              boxHeight: 8,
              padding: 18,
              color: '#334155',
              font: { weight: '700' }
            }
          },
          tooltip: {
            mode: 'index',
            intersect: false,
            callbacks: {
              label: (ctx) => {
                const value = Number(ctx.raw || 0);
                if (ctx.dataset.yAxisID === 'roi') {
                  return `ROI: ${value.toFixed(2)}%`;
                }
                return `Sales: ${money.format(value)}`;
              }
            }
          }
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: { color: '#64748b', font: { weight: '700' } }
          },
          sales: {
            type: 'linear',
            position: 'left',
            beginAtZero: true,
            title: { display: true, text: 'Sales (RM)' },
            grid: { color: 'rgba(148, 163, 184, .26)' },
            ticks: {
              color: '#334155',
              callback: (value) => money.format(Number(value))
            }
          },
          roi: {
            type: 'linear',
            position: 'right',
            beginAtZero: true,
            title: { display: true, text: 'ROI (%)' },
            grid: { drawOnChartArea: false },
            ticks: {
              color: '#334155',
              callback: (value) => `${Number(value).toFixed(0)}%`
            }
          }
        }
      }
    });
  }

  const forecastRevenueLabels = data.forecast_revenue_labels || data.forecast_labels || [];
  const forecastRevenueValues = (data.forecast_revenue || []).map((value) => Number(value) || 0);
  if (document.getElementById('forecastRevenue')) {
    console.debug('[forecast debug] revenue labels received:', forecastRevenueLabels);
    console.debug('[forecast debug] revenue values received:', forecastRevenueValues);
  }

  mkLine('revenueChart', data.revenue_labels || [], data.revenue_values || [], 'Revenue', '#0d6efd');
  mkLine('cashChart', data.revenue_labels || [], data.cash_values || [], 'Cash Flow', '#198754');
  mkLine('forecastRevenue', forecastRevenueLabels, forecastRevenueValues, 'Forecast Revenue', '#6f42c1');
  mkLine('forecastCash', data.forecast_labels || [], data.forecast_cash || [], 'Forecast Cash Flow', '#fd7e14');

  const channelEl = document.getElementById('revenueByChannelChart');
  if (channelEl) {
    const channelRows = data.revenue_by_channel || [];
    const centerText = money.format(Number(data.revenue_by_channel_total || 0));
    const centerLabelPlugin = {
      id: 'revenueChannelCenterLabel',
      afterDraw(chart) {
        const meta = chart.getDatasetMeta(0);
        if (!meta.data.length) return;
        const { ctx, chartArea } = chart;
        const centerX = (chartArea.left + chartArea.right) / 2;
        const centerY = (chartArea.top + chartArea.bottom) / 2;
        ctx.save();
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillStyle = '#6b7280';
        ctx.font = '600 12px system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
        ctx.fillText('Total', centerX, centerY - 12);
        ctx.fillStyle = '#1f2937';
        ctx.font = '700 18px system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
        ctx.fillText(centerText, centerX, centerY + 10);
        ctx.restore();
      }
    };

    new Chart(channelEl, {
      type: 'doughnut',
      data: {
        labels: channelRows.map(row => row.channel),
        datasets: [{
          data: channelRows.map(row => row.revenue),
          backgroundColor: ['#0d6efd', '#198754', '#f59e0b', '#dc2626', '#6f42c1', '#0ea5e9'],
          borderColor: '#ffffff',
          borderWidth: 3,
          hoverOffset: 6
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '68%',
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (ctx) => `${ctx.label}: ${money.format(Number(ctx.raw || 0))}`
            }
          }
        }
      },
      plugins: [centerLabelPlugin]
    });
  }

  const pieEl = document.getElementById('sentimentPie');
  if (pieEl) {
    const sentimentTotal = Number(data.sentiment_total || 0);
    const sentimentCenterPlugin = {
      id: 'sentimentCenterTotal',
      afterDraw(chart) {
        const meta = chart.getDatasetMeta(0);
        if (!meta.data.length) return;
        const { ctx, chartArea } = chart;
        const centerX = (chartArea.left + chartArea.right) / 2;
        const centerY = (chartArea.top + chartArea.bottom) / 2;
        ctx.save();
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillStyle = '#98a2b3';
        ctx.font = '500 14px system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
        ctx.fillText('Total', centerX, centerY - 12);
        ctx.fillStyle = '#0f172a';
        ctx.font = '800 24px system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
        ctx.fillText(String(sentimentTotal), centerX, centerY + 14);
        ctx.restore();
      }
    };

    new Chart(pieEl, {
      type: 'doughnut',
      data: {
        labels: ['Positive', 'Neutral', 'Negative'],
        datasets: [{
          data: [
            data.sentiment_counts.positive || 0,
            data.sentiment_counts.neutral || 0,
            data.sentiment_counts.negative || 0
          ],
          backgroundColor: ['#10b981', '#f59e0b', '#ef4444'],
          borderColor: '#ffffff',
          borderWidth: 8,
          hoverOffset: 8,
          spacing: 3
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        devicePixelRatio: window.devicePixelRatio || 1,
        cutout: '64%',
        rotation: -120,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (ctx) => {
                const value = Number(ctx.raw || 0);
                const pct = sentimentTotal ? Math.round((value / sentimentTotal) * 100) : 0;
                return `${ctx.label}: ${value} (${pct}%)`;
              }
            }
          }
        }
      },
      plugins: [sentimentCenterPlugin]
    });
  }

  const sEl = document.getElementById('sentimentSales');
  if (sEl) {
    new Chart(sEl, {
      type: 'line',
      data: {
        labels: data.sentiment_vs_sales_labels || [],
        datasets: [
          {
            label: 'Revenue',
            data: data.sentiment_vs_sales_revenue || [],
            borderColor: '#0d6efd',
            backgroundColor: '#0d6efd',
            yAxisID: 'y',
            tension: 0.32,
            borderWidth: 3,
            pointRadius: 3,
            pointHoverRadius: 5,
            pointBorderWidth: 2,
            pointBackgroundColor: '#ffffff',
            pointBorderColor: '#0d6efd'
          },
          {
            label: 'Sentiment Index',
            data: data.sentiment_vs_sales_sentiment || [],
            borderColor: '#dc3545',
            backgroundColor: '#dc3545',
            yAxisID: 'y1',
            tension: 0.32,
            borderWidth: 3,
            pointRadius: 3,
            pointHoverRadius: 5,
            pointBorderWidth: 2,
            pointBackgroundColor: '#ffffff',
            pointBorderColor: '#dc3545'
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        devicePixelRatio: window.devicePixelRatio || 1,
        interaction: {
          mode: 'index',
          intersect: false
        },
        plugins: {
          legend: {
            display: true,
            position: 'bottom',
            labels: {
              boxWidth: 10,
              boxHeight: 10,
              usePointStyle: true,
              padding: 18,
              color: '#334155',
              font: { weight: '700' }
            }
          },
          tooltip: {
            mode: 'index',
            intersect: false,
            backgroundColor: '#0f172a',
            titleColor: '#f8fafc',
            bodyColor: '#e2e8f0',
            borderColor: 'rgba(148, 163, 184, .35)',
            borderWidth: 1,
            callbacks: {
              label: (ctx) => {
                const value = Number(ctx.raw || 0);
                if (ctx.dataset.yAxisID === 'y1') {
                  return `Sentiment Index: ${value.toFixed(3)}`;
                }
                return `Revenue: ${money.format(value)}`;
              }
            }
          }
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: {
              color: '#64748b',
              maxRotation: 0,
              autoSkip: true,
              maxTicksLimit: 8
            }
          },
          y: {
            type: 'linear',
            position: 'left',
            beginAtZero: true,
            grid: { color: 'rgba(148, 163, 184, .22)' },
            ticks: {
              color: '#64748b',
              callback: (value) => money.format(Number(value))
            },
            title: {
              display: true,
              text: 'Revenue (RM)',
              color: '#475569',
              font: { weight: '700' }
            }
          },
          y1: {
            type: 'linear',
            position: 'right',
            grid: { drawOnChartArea: false },
            ticks: {
              color: '#64748b',
              callback: (value) => Number(value).toFixed(2)
            },
            title: {
              display: true,
              text: 'Sentiment Index',
              color: '#475569',
              font: { weight: '700' }
            }
          }
        }
      }
    });
  }
})();
