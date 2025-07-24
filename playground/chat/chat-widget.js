// Chat Widget JavaScript
(function() {
  'use strict';

  // State management
  let sessionId = null;
  let isOpen = false;
  let isTyping = false;
  let showingMetadata = false;
  let sessionStartTime = null;
  let messageCount = 0;
  
  // DOM elements
  const elements = {
    fab: null,
    overlay: null,
    sheet: null,
    messagesContainer: null,
    messageInput: null,
    sendButton: null,
    closeButton: null,
    chatForm: null,
    metadataToggle: null,
    metadataContainer: null,
    sessionIdDisplay: null,
    sessionStartTimeDisplay: null,
    messageCountDisplay: null,
    sessionDurationDisplay: null,
    inputArea: null
  };
  
  // Configuration
  const API_CONFIG = {
    baseUrl: 'http://0.0.0.0:8880',
    apiKey: 'tururu',
    endpoints: {
      chat: '/chat'
    }
  };
  
  // Typewriter effect queue
  const charQueue = [];
  let isRendering = false;
  
  // Initialize on DOM load
  document.addEventListener('DOMContentLoaded', init);
  
  function init() {
    // Cache DOM elements
    elements.fab = document.getElementById('chat-fab');
    elements.overlay = document.getElementById('chat-overlay');
    elements.sheet = document.getElementById('chat-sheet');
    elements.messagesContainer = document.getElementById('messages-container');
    elements.messageInput = document.getElementById('message-input');
    elements.sendButton = document.getElementById('send-button');
    elements.closeButton = document.getElementById('close-chat');
    elements.chatForm = document.getElementById('chat-form');
    elements.metadataToggle = document.getElementById('metadata-toggle');
    elements.metadataContainer = document.getElementById('metadata-container');
    elements.sessionIdDisplay = document.getElementById('session-id-display');
    elements.sessionStartTimeDisplay = document.getElementById('session-start-time');
    elements.messageCountDisplay = document.getElementById('message-count');
    elements.sessionDurationDisplay = document.getElementById('session-duration');
    elements.inputArea = document.getElementById('input-area');
    
    // Debug element finding
    console.log('Metadata toggle element:', elements.metadataToggle);
    console.log('Metadata container element:', elements.metadataContainer);
    
    // Generate session ID
    sessionId = new BSON.ObjectID().toHexString();
    sessionStartTime = new Date();
    console.log('Chat initialized with session ID:', sessionId);
    
    // Update metadata displays
    updateMetadataDisplay();
    
    // Attach event listeners
    attachEventListeners();
    
    // Start duration update timer
    setInterval(updateSessionDuration, 60000); // Update every minute
  }
  
  function attachEventListeners() {
    // FAB click
    elements.fab.addEventListener('click', openChat);
    
    // Close button click
    elements.closeButton.addEventListener('click', closeChat);
    
    // Overlay click
    elements.overlay.addEventListener('click', closeChat);
    
    // Metadata toggle click
    if (elements.metadataToggle) {
      elements.metadataToggle.addEventListener('click', toggleMetadataView);
      console.log('Metadata toggle event listener attached');
    } else {
      console.error('Metadata toggle button not found!');
    }
    
    // Form submit
    elements.chatForm.addEventListener('submit', handleFormSubmit);
    
    // Input enter key
    elements.messageInput.addEventListener('keypress', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleFormSubmit(e);
      }
    });
  }
  
  function openChat() {
    isOpen = true;
    
    // Show overlay and sheet
    elements.overlay.classList.remove('hidden');
    elements.sheet.classList.remove('hidden');
    
    // Trigger animations
    requestAnimationFrame(() => {
      elements.overlay.classList.add('sheet-overlay-enter');
      elements.sheet.classList.add('sheet-content-enter');
      elements.overlay.setAttribute('data-state', 'open');
      elements.sheet.setAttribute('data-state', 'open');
    });
    
    // Hide FAB
    elements.fab.classList.add('hidden');
    
    // Focus input
    elements.messageInput.focus();
  }
  
  function closeChat() {
    isOpen = false;
    
    // Trigger exit animations
    elements.overlay.classList.remove('sheet-overlay-enter');
    elements.sheet.classList.remove('sheet-content-enter');
    elements.overlay.classList.add('sheet-overlay-exit');
    elements.sheet.classList.add('sheet-content-exit');
    
    // Update state
    elements.overlay.setAttribute('data-state', 'closed');
    elements.sheet.setAttribute('data-state', 'closed');
    
    // Hide after animation
    setTimeout(() => {
      elements.overlay.classList.add('hidden');
      elements.sheet.classList.add('hidden');
      elements.overlay.classList.remove('sheet-overlay-exit');
      elements.sheet.classList.remove('sheet-content-exit');
      
      // Show FAB
      elements.fab.classList.remove('hidden');
    }, 300);
  }
  
  async function handleFormSubmit(e) {
    e.preventDefault();
    
    const message = elements.messageInput.value.trim();
    if (!message || isTyping) return;
    
    // Disable inputs
    setInputsEnabled(false);
    
    // Add user message
    addMessage('user', message);
    
    // Clear input
    elements.messageInput.value = '';
    
    // Send message to API
    try {
      await sendMessage(message);
    } catch (error) {
      console.error('Error sending message:', error);
      addMessage('agent', 'Lo siento, ha ocurrido un error. Por favor, intenta de nuevo.');
      setInputsEnabled(true);
    }
  }
  
  function addMessage(role, content) {
    const messageDiv = document.createElement('div');
    messageDiv.className = 'flex items-start space-x-2';
    
    if (role === 'user') {
      messageDiv.classList.add('justify-end');
      messageDiv.innerHTML = `
        <div class="bg-primary text-primary-foreground rounded-lg px-4 py-2 max-w-[80%] ml-auto">
          <p class="text-sm">${escapeHtml(content)}</p>
        </div>
        <div class="relative flex h-8 w-8 shrink-0 overflow-hidden rounded-full bg-muted">
          <span class="flex h-full w-full items-center justify-center text-sm">👤</span>
        </div>
      `;
      // Increment message count when user sends a message
      messageCount++;
      updateMetadataDisplay();
    } else {
      const messageContent = document.createElement('div');
      messageContent.className = 'bg-secondary text-secondary-foreground rounded-lg px-4 py-2 max-w-[80%]';
      
      if (content) {
        messageContent.innerHTML = `<div class="text-sm prose prose-sm">${marked.parse(content)}</div>`;
      } else {
        // For streaming responses
        const streamingDiv = document.createElement('div');
        streamingDiv.className = 'text-sm typewriter-text';
        messageContent.appendChild(streamingDiv);
      }
      
      messageDiv.innerHTML = `
        <div class="relative flex h-8 w-8 shrink-0 overflow-hidden rounded-full bg-muted">
          <span class="flex h-full w-full items-center justify-center text-sm">🤖</span>
        </div>
      `;
      messageDiv.appendChild(messageContent);
    }
    
    elements.messagesContainer.appendChild(messageDiv);
    scrollToBottom();
    
    return messageDiv;
  }
  
  async function sendMessage(message) {
    isTyping = true;
    
    // Add agent message container for streaming
    const agentMessageDiv = addMessage('agent');
    const streamingContainer = agentMessageDiv.querySelector('.typewriter-text');
    
    let fullResponse = '';
    
    try {
      const response = await fetch(`${API_CONFIG.baseUrl}${API_CONFIG.endpoints.chat}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Session-Id': sessionId,
          'X-Api-Key': API_CONFIG.apiKey
        },
        body: JSON.stringify({ prompt: message })
      });
      
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      
      // Handle streaming response
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let streamDone = false;
      
      const onStreamComplete = () => {
        if (streamDone) {
          // Replace streaming container with parsed markdown
          const messageContent = agentMessageDiv.querySelector('.bg-secondary');
          messageContent.innerHTML = `<div class="text-sm prose prose-sm">${marked.parse(fullResponse)}</div>`;
          scrollToBottom();
          setInputsEnabled(true);
          isTyping = false;
        }
      };
      
      while (true) {
        const { done, value } = await reader.read();
        
        if (value) {
          const chunk = decoder.decode(value, { stream: true });
          fullResponse += chunk;
          
          // Add to typewriter queue
          charQueue.push(...chunk);
          
          if (!isRendering) {
            renderFromQueue(streamingContainer, onStreamComplete);
          }
        }
        
        if (done) {
          streamDone = true;
          if (!isRendering) {
            onStreamComplete();
          }
          break;
        }
      }
    } catch (error) {
      console.error('Error in sendMessage:', error);
      throw error;
    }
  }
  
  function renderFromQueue(targetDiv, onComplete) {
    if (isRendering) return;
    isRendering = true;
    
    const render = () => {
      if (charQueue.length > 0) {
        // Render multiple characters per frame for faster display
        const charsToRender = Math.min(charQueue.length, 3);
        for (let i = 0; i < charsToRender; i++) {
          targetDiv.textContent += charQueue.shift();
        }
        scrollToBottom();
        requestAnimationFrame(render);
      } else {
        isRendering = false;
        if (onComplete) onComplete();
      }
    };
    
    render();
  }
  
  function setInputsEnabled(enabled) {
    elements.messageInput.disabled = !enabled;
    elements.sendButton.disabled = !enabled;
    
    if (enabled) {
      elements.sendButton.classList.remove('opacity-50', 'cursor-not-allowed');
      elements.messageInput.focus();
    } else {
      elements.sendButton.classList.add('opacity-50', 'cursor-not-allowed');
    }
  }
  
  function scrollToBottom() {
    elements.messagesContainer.scrollTop = elements.messagesContainer.scrollHeight;
  }
  
  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }
  
  
  function toggleMetadataView() {
    console.log('Toggle metadata view called, current state:', showingMetadata);
    showingMetadata = !showingMetadata;
    
    if (showingMetadata) {
      // Hide chat and input, show metadata
      elements.messagesContainer.classList.add('hidden');
      elements.metadataContainer.classList.remove('hidden');
      elements.inputArea.classList.add('hidden');
      
      // Update button icon
      elements.metadataToggle.innerHTML = `
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
        </svg>
      `;
      elements.metadataToggle.setAttribute('aria-label', 'Ver chat');
      elements.metadataToggle.setAttribute('title', 'Ver chat');
      
      // Update metadata display
      updateMetadataDisplay();
      console.log('Metadata view shown');
    } else {
      // Show chat and input, hide metadata
      elements.messagesContainer.classList.remove('hidden');
      elements.metadataContainer.classList.add('hidden');
      elements.inputArea.classList.remove('hidden');
      
      // Update button icon back to info
      elements.metadataToggle.innerHTML = `
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="10"></circle>
          <line x1="12" y1="16" x2="12" y2="12"></line>
          <line x1="12" y1="8" x2="12.01" y2="8"></line>
        </svg>
      `;
      elements.metadataToggle.setAttribute('aria-label', 'Ver metadata');
      elements.metadataToggle.setAttribute('title', 'Ver metadata');
      console.log('Chat view shown');
    }
  }
  
  function updateMetadataDisplay() {
    // Update session ID
    elements.sessionIdDisplay.textContent = sessionId;
    
    // Update session start time
    elements.sessionStartTimeDisplay.textContent = sessionStartTime.toLocaleTimeString('es-ES', {
      hour: '2-digit',
      minute: '2-digit'
    });
    
    // Update message count
    elements.messageCountDisplay.textContent = messageCount;
    
    // Update session duration
    updateSessionDuration();
  }
  
  function updateSessionDuration() {
    if (!sessionStartTime) return;
    
    const now = new Date();
    const durationMs = now - sessionStartTime;
    const durationMinutes = Math.floor(durationMs / 60000);
    
    elements.sessionDurationDisplay.textContent = `${durationMinutes} min`;
  }
  
  // Public API (optional)
  window.ChatWidget = {
    open: openChat,
    close: closeChat,
    isOpen: () => isOpen,
    getSessionId: () => sessionId,
    reset: () => {
      sessionId = new BSON.ObjectID().toHexString();
      sessionStartTime = new Date();
      messageCount = 0;
      showingMetadata = false;
      
      elements.messagesContainer.innerHTML = `
        <div class="flex items-start space-x-2">
          <div class="relative flex h-8 w-8 shrink-0 overflow-hidden rounded-full bg-muted">
            <span class="flex h-full w-full items-center justify-center text-sm">🤖</span>
          </div>
          <div class="bg-secondary text-secondary-foreground rounded-lg px-4 py-2 max-w-[80%]">
            <p class="text-sm">¡Hola! Soy tu asistente virtual. ¿En qué puedo ayudarte hoy?</p>
          </div>
        </div>
      `;
      
      // Show chat view if metadata was showing
      if (showingMetadata) {
        toggleMetadataView();
      }
      
      charQueue.length = 0;
      isRendering = false;
      updateMetadataDisplay();
    }
  };
})();