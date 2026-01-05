/**
 * 显示错误消息
 * @param {string} elementId - 消息元素的ID
 * @param {string} message - 要显示的消息内容
 * @param {number} duration - 显示时长(毫秒)，默认3000ms
 */
function showError(elementId, message, duration = 3000) {
    const element = document.getElementById(elementId);
    if (element) {
        element.textContent = message;
        element.classList.add('show');

        // 移除可能存在的success类
        element.classList.remove('success-message');

        if (duration > 0) {
            setTimeout(() => {
                element.classList.remove('show');
            }, duration);
        }
    }
}

/**
 * 显示成功消息
 * @param {string} elementId - 消息元素的ID
 * @param {string} message - 要显示的消息内容
 * @param {number} duration - 显示时长(毫秒)，默认3000ms
 */
function showSuccess(elementId, message, duration = 3000) {
    const element = document.getElementById(elementId);
    if (element) {
        element.textContent = message;
        element.classList.add('show');

        // 移除可能存在的error类
        element.classList.remove('error-message');

        if (duration > 0) {
            setTimeout(() => {
                element.classList.remove('show');
            }, duration);
        }
    }
}

/**
 * 隐藏消息
 * @param {string} elementId - 消息元素的ID
 */
function hideMessage(elementId) {
    const element = document.getElementById(elementId);
    if (element) {
        element.classList.remove('show');
    }
}

/**
 * 格式化日期时间
 * @param {Date} date - 日期对象
 * @returns {string} 格式化后的日期字符串 (YYYY/MM/DD HH:mm:ss)
 */
function formatDateTime(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');
    const seconds = String(date.getSeconds()).padStart(2, '0');

    return `${year}/${month}/${day} ${hours}:${minutes}:${seconds}`;
}

/**
 * 发送API请求
 * @param {string} url - 请求URL
 * @param {object} options - fetch选项
 * @returns {Promise<object>} 返回响应数据
 */
async function apiRequest(url, options = {}) {
    const defaultOptions = {
        method: 'GET',
        headers: {
            'Content-Type': 'application/json',
        },
        ...options
    };

    try {
        const response = await fetch(url, defaultOptions);
        const data = await response.json();

        return {
            ok: response.ok,
            status: response.status,
            data: data
        };
    } catch (error) {
        console.error('API request error:', error);
        return {
            ok: false,
            status: 0,
            data: { success: false, message: '网络请求失败' }
        };
    }
}

/**
 * 页面跳转
 * @param {string} url - 跳转URL
 * @param {number} delay - 延迟时间(毫秒)，默认0
 */
function navigateTo(url, delay = 0) {
    if (delay > 0) {
        setTimeout(() => {
            window.location.href = url;
        }, delay);
    } else {
        window.location.href = url;
    }
}

/**
 * 表单验证
 * @param {object} rules - 验证规则对象
 * @returns {object} { valid: boolean, message: string }
 */
function validateForm(rules) {
    for (const [field, rule] of Object.entries(rules)) {
        const element = document.getElementById(field);
        if (!element) continue;

        const value = element.value.trim();

        // 必填验证
        if (rule.required && !value) {
            return { valid: false, message: rule.requiredMessage || `请输入${rule.label || field}` };
        }

        // 最小长度验证
        if (rule.minLength && value.length < rule.minLength) {
            return { valid: false, message: rule.minLengthMessage || `${rule.label || field}长度至少为${rule.minLength}位` };
        }

        // 最大长度验证
        if (rule.maxLength && value.length > rule.maxLength) {
            return { valid: false, message: rule.maxLengthMessage || `${rule.label || field}长度不能超过${rule.maxLength}位` };
        }

        // 自定义验证函数
        if (rule.validator && typeof rule.validator === 'function') {
            const result = rule.validator(value);
            if (!result.valid) {
                return result;
            }
        }
    }

    return { valid: true };
}
