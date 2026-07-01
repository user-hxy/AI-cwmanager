/* ========== 财务管理系统 - JavaScript ========== */

// 侧边栏切换
function toggleSidebar() {
    var s = document.getElementById('sidebar');
    s.classList.toggle('open');
}

// 移动端触摸关闭侧边栏
function closeSidebar() {
    var s = document.getElementById('sidebar');
    if (window.innerWidth <= 991 && s.classList.contains('open')) {
        s.classList.remove('open');
    }
}

document.addEventListener('DOMContentLoaded', function() {
    var mainContent = document.getElementById('mainContent');
    if (mainContent) {
        // 点击/触摸主区域关闭侧边栏
        mainContent.addEventListener('click', function(e) {
            if (!e.target.closest('#sidebarToggle') && !e.target.closest('.sidebar')) {
                closeSidebar();
            }
        });
        // iOS 触摸
        mainContent.addEventListener('touchstart', function(e) {
            if (!e.target.closest('#sidebarToggle') && !e.target.closest('.sidebar')) {
                closeSidebar();
            }
        });
    }
    // 侧边栏内链接点击后自动关闭（移动端）
    document.querySelectorAll('.sidebar .nav-item').forEach(function(el) {
        el.addEventListener('click', function() { closeSidebar(); });
    });

    // 初始化tooltip
    var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function(el) {
        return new bootstrap.Tooltip(el);
    });

    // 报表数值千分符格式化
    document.querySelectorAll('.table-responsive table.table').forEach(function(tbl) {
        tbl.querySelectorAll('td').forEach(function(td) {
            var txt = td.textContent.trim();
            if (/^-?\d+\.\d{2}$/.test(txt)) {
                td.textContent = formatMoney(parseFloat(txt));
            }
        });
    });
});

// 工具：格式化金额
function formatMoney(amount) {
    return Number(amount).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// 工具：获取当前期间
function getCurrentPeriod() {
    const now = new Date();
    return now.getFullYear() + '-' + String(now.getMonth() + 1).padStart(2, '0');
}
