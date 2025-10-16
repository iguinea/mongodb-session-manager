/**
 * Reusable UI Components for Session Viewer
 *
 * This file contains pure functions for rendering UI components.
 * All components return HTML strings or DOM elements.
 */

// Initialize dayjs with relative time plugin
dayjs.extend(dayjs_plugin_relativeTime);

/**
 * Format utilities
 */
const Format = {
  /**
   * Format date using dayjs
   */
  date(dateString, format = 'YYYY-MM-DD HH:mm:ss') {
    return dayjs(dateString).format(format);
  },

  /**
   * Format date as relative time (e.g., "2 hours ago")
   */
  relativeTime(dateString) {
    return dayjs(dateString).fromNow();
  },

  /**
   * Format large numbers with commas
   */
  number(num) {
    return new Intl.NumberFormat().format(num);
  },

  /**
   * Truncate text with ellipsis
   */
  truncate(text, maxLength = 50) {
    if (!text) return '';
    if (text.length <= maxLength) return text;
    return text.substring(0, maxLength) + '...';
  }
};

/**
 * Session Card Component
 * Renders a session preview card for the results list
 */
function renderSessionCard(session) {
  const card = document.createElement('div');
  card.className = 'p-4 hover:bg-gray-50 cursor-pointer transition-colors fade-in';
  card.dataset.sessionId = session.session_id;

  card.innerHTML = `
    <div class="flex items-start justify-between mb-2">
      <div class="flex-1 min-w-0">
        <p class="text-sm font-medium text-gray-900 truncate">
          ${session.session_id}
        </p>
        <p class="text-xs text-gray-500">
          ${Format.relativeTime(session.created_at)}
        </p>
      </div>
      <div class="ml-2">
        <svg class="w-5 h-5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"></path>
        </svg>
      </div>
    </div>

    <div class="flex items-center space-x-4 text-xs text-gray-500">
      <span class="flex items-center">
        <svg class="w-4 h-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"></path>
        </svg>
        ${session.agents_count} ${session.agents_count === 1 ? 'agente' : 'agentes'}
      </span>
      <span class="flex items-center">
        <svg class="w-4 h-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z"></path>
        </svg>
        ${session.messages_count} mensajes
      </span>
      ${session.feedbacks_count > 0 ? `
        <span class="flex items-center text-primary-600">
          <svg class="w-4 h-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14 10h4.764a2 2 0 011.789 2.894l-3.5 7A2 2 0 0115.263 21h-4.017c-.163 0-.326-.02-.485-.06L7 20m7-10V5a2 2 0 00-2-2h-.095c-.5 0-.905.405-.905.905 0 .714-.211 1.412-.608 2.006L7 11v9m7-10h-2M7 20H5a2 2 0 01-2-2v-6a2 2 0 012-2h2.5"></path>
          </svg>
          ${session.feedbacks_count}
        </span>
      ` : ''}
    </div>

    ${Object.keys(session.metadata).length > 0 ? `
      <div class="mt-2 pt-2 border-t border-gray-100">
        <div class="flex flex-wrap gap-1">
          ${Object.entries(session.metadata).slice(0, 3).map(([key, value]) => `
            <span class="inline-flex items-center px-2 py-0.5 rounded text-xs bg-gray-100 text-gray-700">
              <span class="font-medium">${key}:</span>
              <span class="ml-1">${Format.truncate(String(value), 20)}</span>
            </span>
          `).join('')}
          ${Object.keys(session.metadata).length > 3 ? `
            <span class="inline-flex items-center px-2 py-0.5 rounded text-xs bg-gray-100 text-gray-500">
              +${Object.keys(session.metadata).length - 3} más
            </span>
          ` : ''}
        </div>
      </div>
    ` : ''}
  `;

  return card;
}

/**
 * Parse Message Content
 * Extracts text, toolUse, and toolResult from message content array
 */
function parseMessageContent(content) {
  const parts = [];

  if (!content || !Array.isArray(content)) {
    return parts;
  }

  content.forEach(item => {
    // Text content
    if (item.text) {
      parts.push({
        type: 'text',
        content: item.text
      });
    }

    // Tool use (tool call)
    if (item.toolUse) {
      parts.push({
        type: 'tool_use',
        toolUseId: item.toolUse.toolUseId,
        toolName: item.toolUse.name,
        input: item.toolUse.input
      });
    }

    // Tool result
    if (item.toolResult) {
      parts.push({
        type: 'tool_result',
        toolUseId: item.toolResult.toolUseId,
        status: item.toolResult.status,
        content: item.toolResult.content,
        structuredContent: item.toolResult.structuredContent
      });
    }
  });

  return parts;
}

/**
 * Render Tool Use Block
 * Renders a tool call with name and input parameters
 */
function renderToolUse(toolUse, isUser) {
  const container = document.createElement('div');
  container.className = `tool-use-block ${isUser ? 'tool-use-user' : 'tool-use-assistant'}`;

  // Header
  const header = document.createElement('div');
  header.className = 'tool-header';
  header.innerHTML = `
    <span class="tool-badge tool-badge-use">🔧 Tool Call</span>
    <span class="tool-name">${toolUse.toolName}</span>
  `;
  container.appendChild(header);

  // Details with renderjson
  const details = document.createElement('details');
  details.className = 'tool-details';

  const summary = document.createElement('summary');
  summary.className = 'tool-summary';
  summary.textContent = 'View input parameters';
  details.appendChild(summary);

  // Content container for renderjson
  const contentDiv = document.createElement('div');
  contentDiv.className = 'tool-content tool-json-content';

  // Configure and render JSON
  renderjson.set_show_to_level(2); // Expand first 2 levels by default
  renderjson.set_max_string_length(100); // Truncate long strings
  const jsonTree = renderjson(toolUse.input);
  contentDiv.appendChild(jsonTree);

  details.appendChild(contentDiv);
  container.appendChild(details);

  return container;
}

/**
 * Render Tool Result Block
 * Renders a tool result with status and output
 */
function renderToolResult(toolResult, isUser) {
  const container = document.createElement('div');
  container.className = `tool-result-block ${isUser ? 'tool-result-user' : 'tool-result-assistant'}`;

  const isSuccess = toolResult.status === 'success';
  const badgeClass = isSuccess ? 'tool-badge-success' : 'tool-badge-error';
  const badgeIcon = isSuccess ? '✅' : '❌';
  const badgeText = isSuccess ? 'Success' : 'Error';

  // Header
  const header = document.createElement('div');
  header.className = 'tool-header';
  header.innerHTML = `
    <span class="tool-badge ${badgeClass}">${badgeIcon} ${badgeText}</span>
    <span class="tool-status">${toolResult.status}</span>
  `;
  container.appendChild(header);

  // Details
  const details = document.createElement('details');
  details.className = 'tool-details';

  const summary = document.createElement('summary');
  summary.className = 'tool-summary';
  summary.textContent = 'View result';
  details.appendChild(summary);

  // Content container
  const contentDiv = document.createElement('div');
  contentDiv.className = 'tool-content tool-json-content';

  // Extract and render result content
  let hasContent = false;

  // Try structuredContent first (it's already an object)
  if (toolResult.structuredContent) {
    renderjson.set_show_to_level(2);
    renderjson.set_max_string_length(100);
    const jsonTree = renderjson(toolResult.structuredContent);
    contentDiv.appendChild(jsonTree);
    hasContent = true;
  }
  // Then try content array
  else if (toolResult.content && Array.isArray(toolResult.content)) {
    const textContent = toolResult.content
      .filter(c => c.text)
      .map(c => c.text)
      .join('\n');

    // Try to parse as JSON
    try {
      const parsed = JSON.parse(textContent);
      renderjson.set_show_to_level(2);
      renderjson.set_max_string_length(100);
      const jsonTree = renderjson(parsed);
      contentDiv.appendChild(jsonTree);
      hasContent = true;
    } catch (e) {
      // Not JSON, show as plain text
      const pre = document.createElement('pre');
      pre.className = 'tool-text-content';
      pre.textContent = textContent;
      contentDiv.appendChild(pre);
      hasContent = true;
    }
  }

  // No content fallback
  if (!hasContent) {
    const noContent = document.createElement('p');
    noContent.className = 'text-gray-500 italic';
    noContent.textContent = 'No content';
    contentDiv.appendChild(noContent);
  }

  details.appendChild(contentDiv);
  container.appendChild(details);

  return container;
}

/**
 * Timeline Message Component
 * Renders a message in the timeline
 */
function renderTimelineMessage(item) {
  const isUser = item.role === 'user';
  const container = document.createElement('div');
  container.className = `flex ${isUser ? 'justify-end' : 'justify-start'} fade-in`;

  // Parse message content
  const contentParts = parseMessageContent(item.content);

  // Create wrapper div
  const wrapper = document.createElement('div');
  wrapper.className = `max-w-[85%] ${isUser ? 'ml-auto' : 'mr-auto'}`;

  // Add agent badge and timestamp for assistant messages
  if (!isUser) {
    const header = document.createElement('div');
    header.className = 'flex items-center space-x-2 mb-1';
    header.innerHTML = `
      <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-primary-100 text-primary-800">
        ${item.agent_id}
      </span>
      <span class="text-xs text-gray-500">
        ${Format.date(item.timestamp)}
      </span>
    `;
    wrapper.appendChild(header);
  }

  // Create message bubble container
  const bubble = document.createElement('div');
  bubble.className = `rounded-lg px-4 py-3 ${isUser ? 'bg-primary-600 text-white user-message' : 'bg-gray-100 text-gray-900 assistant-message'}`;

  // Render each content part
  if (contentParts.length === 0) {
    // No content - show placeholder
    const zeroMd = document.createElement('zero-md');
    const script = document.createElement('script');
    script.type = 'text/markdown';
    script.textContent = '*Sin contenido*';
    zeroMd.appendChild(script);
    bubble.appendChild(zeroMd);
  } else {
    contentParts.forEach((part, index) => {
      if (part.type === 'text') {
        // Render text content with zero-md
        const zeroMd = document.createElement('zero-md');

        // Add markdown content
        const script = document.createElement('script');
        script.type = 'text/markdown';
        script.textContent = part.content;
        zeroMd.appendChild(script);

        // Add custom styles to zero-md
        const style = document.createElement('template');
        style.innerHTML = `
          <style>
            :host {
              --markdown-font-size: 0.875rem;
              --markdown-line-height: 1.5;
            }

            /* Override default styles for better integration */
            p { margin: 0.5em 0; }
            p:first-child { margin-top: 0; }
            p:last-child { margin-bottom: 0; }

            code {
              background: ${isUser ? 'rgba(255, 255, 255, 0.1)' : 'rgba(0, 0, 0, 0.05)'};
              padding: 0.2em 0.4em;
              border-radius: 0.25rem;
              font-size: 0.85em;
            }

            pre {
              background: ${isUser ? 'rgba(255, 255, 255, 0.1)' : 'rgba(0, 0, 0, 0.05)'};
              padding: 1em;
              border-radius: 0.5rem;
              overflow-x: auto;
            }

            pre code {
              background: transparent;
              padding: 0;
            }
          </style>
        `;
        zeroMd.appendChild(style);

        bubble.appendChild(zeroMd);
      } else if (part.type === 'tool_use') {
        // Render tool call
        const toolUseEl = renderToolUse(part, isUser);
        bubble.appendChild(toolUseEl);
      } else if (part.type === 'tool_result') {
        // Render tool result
        const toolResultEl = renderToolResult(part, isUser);
        bubble.appendChild(toolResultEl);
      }

      // Add spacing between parts (except for the last one)
      if (index < contentParts.length - 1) {
        const spacer = document.createElement('div');
        spacer.className = 'mt-3';
        bubble.appendChild(spacer);
      }
    });
  }

  // Add metrics if available
  if (item.metrics) {
    const metrics = document.createElement('div');
    metrics.className = `mt-2 pt-2 border-t ${isUser ? 'border-primary-500' : 'border-gray-200'}`;
    metrics.innerHTML = `
      <div class="flex items-center space-x-3 text-xs ${isUser ? 'text-primary-100' : 'text-gray-500'}">
        <span title="Tokens">
          🔢 ${Format.number(item.metrics.accumulated_usage?.totalTokens || 0)}
        </span>
        <span title="Latencia">
          ⏱️ ${item.metrics.accumulated_metrics?.latencyMs || 0}ms
        </span>
      </div>
    `;
    bubble.appendChild(metrics);
  }

  wrapper.appendChild(bubble);

  // Add timestamp for user messages
  if (isUser) {
    const footer = document.createElement('div');
    footer.className = 'text-right mt-1';
    footer.innerHTML = `
      <span class="text-xs text-gray-500">
        ${Format.date(item.timestamp)}
      </span>
    `;
    wrapper.appendChild(footer);
  }

  container.appendChild(wrapper);
  return container;
}

/**
 * Timeline Feedback Component
 * Renders a feedback item in the timeline
 */
function renderTimelineFeedback(item) {
  const container = document.createElement('div');
  container.className = 'flex justify-center fade-in';

  const ratingColors = {
    'up': 'border-green-200 bg-green-50',
    'down': 'border-red-200 bg-red-50',
    'null': 'border-gray-200 bg-gray-50'
  };

  const ratingIcons = {
    'up': '👍',
    'down': '👎',
    'null': '💬'
  };

  const rating = item.rating || 'null';
  const colorClass = ratingColors[rating];
  const icon = ratingIcons[rating];

  container.innerHTML = `
    <div class="w-full max-w-md">
      <div class="border-2 ${colorClass} rounded-lg px-4 py-3">
        <div class="flex items-start space-x-3">
          <span class="text-2xl">${icon}</span>
          <div class="flex-1 min-w-0">
            <div class="flex items-center justify-between mb-1">
              <span class="text-sm font-medium text-gray-900">
                Feedback ${rating === 'up' ? 'Positivo' : rating === 'down' ? 'Negativo' : 'Neutral'}
              </span>
              <span class="text-xs text-gray-500">
                ${Format.date(item.timestamp, 'HH:mm:ss')}
              </span>
            </div>
            ${item.comment ? `
              <p class="text-sm text-gray-700">
                "${item.comment}"
              </p>
            ` : ''}
          </div>
        </div>
      </div>
    </div>
  `;

  return container;
}

/**
 * Agent Summary Component
 * Renders an agent summary badge
 */
function renderAgentSummary(agentId, summary) {
  const div = document.createElement('div');
  div.className = 'p-3 bg-gray-50 rounded-md';

  // Header with agent ID and message count
  const header = document.createElement('div');
  header.className = 'flex items-center justify-between mb-2';
  header.innerHTML = `
    <span class="font-medium text-sm text-gray-900">${agentId}</span>
    <span class="text-xs text-gray-500">${summary.messages_count} mensajes</span>
  `;
  div.appendChild(header);

  // Model info
  if (summary.model) {
    const modelInfo = document.createElement('p');
    modelInfo.className = 'text-xs text-gray-600 mb-1';
    modelInfo.innerHTML = `
      <span class="font-medium">Model:</span> ${Format.truncate(summary.model, 40)}
    `;
    div.appendChild(modelInfo);
  }

  // System prompt with modal button
  if (summary.system_prompt) {
    const promptBtn = document.createElement('button');
    promptBtn.className = 'mt-2 text-xs font-medium text-gray-700 hover:text-primary-600 transition-colors flex items-center space-x-1';
    promptBtn.innerHTML = `
      <span>📝</span>
      <span>Ver System Prompt</span>
    `;

    // Open modal on click
    promptBtn.addEventListener('click', () => {
      window.openPromptModal(summary.system_prompt);
    });

    div.appendChild(promptBtn);
  }

  return div;
}

/**
 * Metadata Display Component
 * Renders metadata key-value pairs using renderjson for interactive JSON visualization
 */
function renderMetadata(metadata) {
  const container = document.createElement('div');
  container.className = 'metadata-json-container';

  if (Object.keys(metadata).length === 0) {
    container.innerHTML = '<p class="text-sm text-gray-500 italic">Sin metadata</p>';
    return container;
  }

  // Configure renderjson
  renderjson.set_show_to_level(2);  // Show first two levels expanded
  renderjson.set_max_string_length(100);  // Truncate long strings

  // Render metadata as interactive JSON tree
  const jsonTree = renderjson(metadata);
  jsonTree.className = 'metadata-renderjson';
  container.appendChild(jsonTree);

  return container;
}

/**
 * Dynamic Filter Component
 * Renders a filter row with field selector and type-appropriate value input
 *
 * @param {Array} fieldInfos - Array of FieldInfo objects from backend
 * @returns {HTMLElement} Filter row element
 *
 * FieldInfo structure:
 * {
 *   field: "metadata.status",
 *   type: "enum",
 *   values: ["active", "completed"]
 * }
 */
function renderDynamicFilter(fieldInfos = []) {
  const container = document.createElement('div');
  container.className = 'flex items-center space-x-2 p-2 bg-gray-50 rounded-md';

  // Field selector
  const fieldSelect = document.createElement('select');
  fieldSelect.className = 'filter-field flex-1 px-2 py-1 text-sm border border-gray-300 rounded-md focus:ring-1 focus:ring-primary-500 focus:border-transparent';

  // Default option
  const defaultOption = document.createElement('option');
  defaultOption.value = '';
  defaultOption.textContent = 'Seleccionar campo...';
  fieldSelect.appendChild(defaultOption);

  // Add field options with type information stored in dataset
  fieldInfos.forEach(fieldInfo => {
    const option = document.createElement('option');
    option.value = fieldInfo.field;
    option.textContent = fieldInfo.field;
    option.dataset.type = fieldInfo.type;

    // Store enum values as JSON if present
    if (fieldInfo.type === 'enum' && fieldInfo.values) {
      option.dataset.values = JSON.stringify(fieldInfo.values);
    }

    fieldSelect.appendChild(option);
  });

  // Value input container (will be replaced when field changes)
  const valueContainer = document.createElement('div');
  valueContainer.className = 'filter-value-container flex-1';

  // Initial value input (generic text)
  const initialInput = document.createElement('input');
  initialInput.type = 'text';
  initialInput.className = 'filter-value w-full px-2 py-1 text-sm border border-gray-300 rounded-md focus:ring-1 focus:ring-primary-500 focus:border-transparent';
  initialInput.placeholder = 'Valor...';
  valueContainer.appendChild(initialInput);

  // Remove button
  const removeBtn = document.createElement('button');
  removeBtn.className = 'remove-filter-btn p-1 text-gray-400 hover:text-red-600 transition-colors';
  removeBtn.innerHTML = `
    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
    </svg>
  `;

  /**
   * Event handler: When field is selected, render appropriate value input
   */
  fieldSelect.addEventListener('change', () => {
    const selectedOption = fieldSelect.options[fieldSelect.selectedIndex];
    const fieldType = selectedOption.dataset.type;
    const enumValues = selectedOption.dataset.values;

    // Clear current value input
    valueContainer.innerHTML = '';

    // Render type-appropriate input control
    let newInput;

    switch (fieldType) {
      case 'enum':
        // Dropdown with predefined values
        newInput = document.createElement('select');
        newInput.className = 'filter-value w-full px-2 py-1 text-sm border border-gray-300 rounded-md focus:ring-1 focus:ring-primary-500 focus:border-transparent';

        // Default option
        const defaultOpt = document.createElement('option');
        defaultOpt.value = '';
        defaultOpt.textContent = 'Seleccionar valor...';
        newInput.appendChild(defaultOpt);

        // Enum values from backend
        if (enumValues) {
          const values = JSON.parse(enumValues);
          values.forEach(value => {
            const opt = document.createElement('option');
            opt.value = value;
            opt.textContent = value;
            newInput.appendChild(opt);
          });
        }
        break;

      case 'date':
        // Date picker
        newInput = document.createElement('input');
        newInput.type = 'date';
        newInput.className = 'filter-value w-full px-2 py-1 text-sm border border-gray-300 rounded-md focus:ring-1 focus:ring-primary-500 focus:border-transparent';
        break;

      case 'number':
        // Number input
        newInput = document.createElement('input');
        newInput.type = 'number';
        newInput.className = 'filter-value w-full px-2 py-1 text-sm border border-gray-300 rounded-md focus:ring-1 focus:ring-primary-500 focus:border-transparent';
        newInput.placeholder = 'Valor numérico...';
        break;

      case 'boolean':
        // True/False dropdown
        newInput = document.createElement('select');
        newInput.className = 'filter-value w-full px-2 py-1 text-sm border border-gray-300 rounded-md focus:ring-1 focus:ring-primary-500 focus:border-transparent';

        ['', 'true', 'false'].forEach(val => {
          const opt = document.createElement('option');
          opt.value = val;
          opt.textContent = val === '' ? 'Seleccionar...' : val;
          newInput.appendChild(opt);
        });
        break;

      case 'string':
      default:
        // Text input (default fallback)
        newInput = document.createElement('input');
        newInput.type = 'text';
        newInput.className = 'filter-value w-full px-2 py-1 text-sm border border-gray-300 rounded-md focus:ring-1 focus:ring-primary-500 focus:border-transparent';
        newInput.placeholder = 'Valor...';
        break;
    }

    // Add new input to container
    valueContainer.appendChild(newInput);
  });

  // Assemble filter row
  container.appendChild(fieldSelect);
  container.appendChild(valueContainer);
  container.appendChild(removeBtn);

  return container;
}

/**
 * Empty State Component
 */
function renderEmptyState(title, message, iconPath) {
  return `
    <div class="p-8 text-center">
      <svg class="mx-auto h-12 w-12 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="${iconPath}"></path>
      </svg>
      <h3 class="mt-2 text-sm font-medium text-gray-900">${title}</h3>
      <p class="mt-1 text-sm text-gray-500">${message}</p>
    </div>
  `;
}

/**
 * Loading Spinner Component
 */
function renderLoadingSpinner() {
  return '<div class="flex justify-center p-8"><div class="spinner"></div></div>';
}

// Export components for use in viewer.js
window.Components = {
  Format,
  renderSessionCard,
  renderTimelineMessage,
  renderTimelineFeedback,
  renderAgentSummary,
  renderMetadata,
  renderDynamicFilter,
  renderEmptyState,
  renderLoadingSpinner
};
