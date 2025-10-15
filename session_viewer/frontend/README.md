# Session Viewer Frontend

Modern web interface for viewing and analyzing MongoDB sessions from the Session Manager.

## Features

- **Authentication System**: Password protection with elegant dark gradient modal on startup
- **Resizable Panels**: Drag-to-resize left panel (Filters + Results) with localStorage persistence
- **Interactive JSON Visualization**: Collapsible JSON trees using renderjson for tool calls, results, and metadata
- **Direct Session Loading**: Load specific sessions via URL parameter (`?session_id=<ID>`)
- **Dynamic Filtering**: Add/remove metadata filters at runtime
- **Search Sessions**: Find sessions by ID, metadata fields, or date range
- **Pagination**: Navigate through large result sets
- **Unified Timeline**: View messages from all agents chronologically
- **Tool Call Visualization**: See tool calls and results with color-coded badges and collapsible JSON display
- **System Prompt Display**: Full markdown-rendered system prompts in agent summary
- **Feedback Integration**: See user feedbacks in context
- **Responsive Design**: Works on desktop, tablet, and mobile
- **Real-time Health Check**: Monitor backend connectivity
- **Custom Branding**: Blue document/list favicon visible in browser tabs

## Architecture

### Technology Stack

- **CSS Framework**: Tailwind CSS (via CDN)
- **JavaScript**: Vanilla JS with ES6 classes (OOP)
- **Libraries**:
  - `zero-md`: Web component for markdown rendering with syntax highlighting
  - `renderjson`: Interactive JSON tree visualization
  - `js-sha256`: SHA-256 password hashing for authentication
  - `dayjs`: Date/time formatting
  - `axios`: HTTP client for API calls

### Project Structure

```
frontend/
├── index.html         # Main UI with 3-panel layout
├── viewer.js          # Application logic (classes)
├── components.js      # Reusable UI components
├── Makefile          # Development commands
└── README.md         # This file
```

### Classes

#### `APIClient`
Handles all HTTP communication with the backend.

**Methods:**
- `checkHealth()`: Check backend health
- `getMetadataFields()`: Get available metadata fields
- `searchSessions()`: Search sessions with filters
- `getSessionDetail()`: Get complete session data

#### `FilterPanel`
Manages the search filter UI.

**Features:**
- Session ID search
- Date range filtering
- Dynamic metadata filters (add/remove)
- Load available fields from backend

#### `ResultsList`
Displays search results with pagination.

**Features:**
- Session preview cards
- Pagination controls
- Loading/empty states
- Click to view detail

#### `SessionDetail`
Shows complete session information.

**Features:**
- Session metadata display
- Agents summary
- Unified chronological timeline
- Message rendering with markdown
- Feedback indicators
- Metrics display (tokens, latency)

#### `SessionViewer`
Main orchestrator that coordinates all components.

## Usage

### Start the Frontend

```bash
# Using Makefile
make run

# Or directly with Python
python3 -m http.server 8883
```

The frontend will be available at http://localhost:8883

### Requirements

- Python 3 (for HTTP server)
- Backend API running on http://localhost:8882

### Authentication

On first load, you'll see an authentication modal:

1. **Dark Gradient Background**: Elegant dark UI with logo watermark
2. **Enter Password**: Default is `123456` (configured in backend `.env`)
3. **Password Hashing**: Password hashed with SHA-256 before sending to backend
4. **No Persistence**: Password NOT stored in localStorage - required on every page load/refresh
5. **Unlimited Retries**: Enter password again if incorrect

**Security:**
- Password never travels as plain text (SHA-256 hash only)
- Hash stored in memory only (lost on browser close)
- All API requests include `X-Password` header with hash
- Modal blocks access to application until authenticated

## Configuration

### API Endpoint

The frontend connects to the backend API at:
```javascript
const API_BASE_URL = 'http://localhost:8882/api/v1';
```

To change this, edit the `APIClient` constructor in `viewer.js`:

```javascript
class APIClient {
  constructor(baseURL = 'http://your-backend:port/api/v1') {
    // ...
  }
}
```

## Features Guide

### Authentication

**First Time Access:**
1. Open http://localhost:8883
2. See dark modal with logo and password prompt
3. Enter password (default: `123456`)
4. Click "Ingresar" or press Enter
5. On success: Modal disappears, application loads
6. On failure: Error message shows, try again

**Password Required:**
- Every time you open the page
- After browser refresh (F5)
- After closing and reopening browser tab
- Password is NOT saved anywhere

### Resizable Panels

The left panel (Filters + Results) can be resized:

1. **Find Handle**: Vertical bar between left and right panels
2. **Drag to Resize**: Click and drag left/right
3. **Constraints**: Minimum 20%, maximum 70% of screen width
4. **Persistence**: Width saved to localStorage automatically
5. **Visual Feedback**: Cursor changes to resize icon, handle highlights on hover
6. **Mobile**: Resizing disabled on mobile (panels stack vertically)

**Tips:**
- Wider left panel: More room for filters and results
- Narrower left panel: More room for session detail content
- Double-click handle: Reset to default width (future feature)

### Interactive JSON Visualization

JSON data is displayed as interactive collapsible trees:

**Where Used:**
- Tool call input parameters
- Tool result outputs
- Session metadata display

**Features:**
- **Expand/Collapse**: Click any object/array to toggle
- **Syntax Highlighting**: Color-coded types (strings=red, numbers=blue, keys=purple)
- **Default Depth**: Shows 2 levels by default, deeper levels collapsed
- **String Truncation**: Long strings truncated to 100 characters
- **Expand All/Collapse All**: Buttons in metadata section for bulk operations

**Usage:**
- Click `{...}` or `[...]` to expand objects/arrays
- Click again to collapse
- Nested structures remain collapsible at each level
- Better than plain JSON text for exploring complex data

### Direct Session Loading

Load specific sessions directly via URL:

**URL Format:**
```
http://localhost:8883?session_id=<SESSION_ID>
```

**Example:**
```
http://localhost:8883?session_id=68ee8a6e8ff935ffff0f7b85
```

**Behavior:**
1. Page loads with authentication modal
2. After successful login, automatically searches for the session
3. Session detail displayed immediately if found
4. Useful for sharing links to specific sessions

**Use Cases:**
- Share session links with team members
- Bookmark important sessions
- Direct links from other tools/dashboards
- Quick access without manual search

### Search Sessions

1. **By Session ID**: Enter full or partial session ID
2. **By Date Range**: Select start and/or end date
3. **By Metadata**: Click "Agregar Filtro" to add custom metadata filters
   - Select field from dropdown
   - Enter search value
   - Add multiple filters (AND logic)
4. Click "Buscar Sesiones"

### View Session Detail

1. Search for sessions
2. Click on a session card in the results
3. View complete information:
   - Session metadata (expandable)
   - Agents involved with full system prompts (expandable)
   - Complete timeline with messages, tool calls, and feedbacks

### Tool Call Visualization

When agents use tools, you'll see:
- **🔧 Tool Calls**: Blue badge with tool name and collapsible JSON input
- **✅ Success Results**: Green badge with collapsible output
- **❌ Error Results**: Red badge with error details
- Click "View input parameters" or "View result" to expand/collapse details

### System Prompts

In the Agents Summary section:
- Click **"📝 System Prompt"** to expand the full prompt
- Prompts are rendered as markdown with proper formatting
- Supports code blocks, lists, emphasis, and other markdown features
- Scrollable area for long prompts (max 300px height)

### Navigate Results

- Use "Anterior" / "Siguiente" buttons for pagination
- View page number and total pages
- Each page shows 20 results by default

### Clear Filters

Click "Limpiar Filtros" to:
- Clear all input fields
- Remove all dynamic filters
- Reset the results list

## UI Components

### Session Card

Displays session preview with:
- Session ID
- Creation date (relative time)
- Agent count
- Message count
- Feedback count
- Sample metadata (first 3 fields)

### Timeline

#### User Messages
- Blue background
- Right-aligned
- Timestamp below

#### Assistant Messages
- Gray background
- Left-aligned
- Agent badge
- Metrics (tokens, latency)
- Timestamp above
- **NEW**: Tool calls and results displayed inline

#### Tool Calls (🔧)
- Blue badge and border
- Tool name prominently displayed
- Collapsible JSON input parameters
- Appears within assistant messages

#### Tool Results (✅/❌)
- Green badge for success, red for errors
- Status indicator (success/error)
- Collapsible output display
- JSON or text format depending on result type

#### Feedbacks
- Centered badges
- Color-coded by rating:
  - Green: Positive (👍)
  - Red: Negative (👎)
  - Gray: Neutral (💬)
- Comment text
- Timestamp

## Customization

### Styling

The UI uses Tailwind CSS utility classes. To customize:

1. **Colors**: Edit the Tailwind config in `index.html`:
```javascript
tailwind.config = {
  theme: {
    extend: {
      colors: {
        primary: {
          // Your colors here
        }
      }
    }
  }
}
```

2. **Layout**: Modify grid classes in `index.html`
3. **Components**: Edit component functions in `components.js`

### Pagination

Default page size is 20. To change it, edit `ResultsList` in `viewer.js`:

```javascript
constructor(container, onSessionSelect) {
  // ...
  this.pageSize = 50; // Change to desired size
}
```

## Development

### File Organization

- **index.html**: Structure and layout
- **components.js**: Pure rendering functions
- **viewer.js**: Application logic and state

### Adding New Features

1. **New Component**: Add to `components.js`
```javascript
function renderMyComponent(data) {
  // Return DOM element or HTML string
}
```

2. **New Class**: Add to `viewer.js`
```javascript
class MyFeature {
  constructor() {
    this.init();
  }

  init() {
    // Setup
  }
}
```

3. **Integrate**: Use in `SessionViewer.init()`

### Debugging

1. Open browser DevTools (F12)
2. Check Console for errors
3. Use Network tab to inspect API calls
4. Check Elements tab for DOM structure

**Common Issues:**
- Backend not running: Check health indicator (top right)
- CORS errors: Verify backend CORS configuration
- Blank page: Check console for JavaScript errors

## Browser Support

- Chrome/Edge: ✅ Fully supported
- Firefox: ✅ Fully supported
- Safari: ✅ Fully supported
- IE11: ❌ Not supported (uses ES6 classes)

## Performance

- Lightweight: No build step required
- Fast: Vanilla JS with minimal dependencies
- CDN Libraries: Cached by browser
- Lazy Loading: Only loads session detail on demand

## Accessibility

- Semantic HTML
- ARIA labels on interactive elements
- Keyboard navigation support
- Focus indicators
- Screen reader friendly

## Security

### Authentication
- **Password Protection**: Required on every page load
- **SHA-256 Hashing**: Password hashed before sending to backend (using js-sha256 library)
- **No Persistence**: Password/hash NOT stored in localStorage or sessionStorage
- **Memory Only**: Hash stored in JavaScript memory, lost on page close
- **Header-based**: All API requests include `X-Password` header

### Other Security Measures
- **XSS Protection**: Uses `textContent` where applicable
- **CORS**: Backend handles origin validation
- **No Sensitive Data**: No credentials or sensitive data in localStorage
- **HTTPS Ready**: Works with HTTPS in production (use reverse proxy)

## Testing

### Manual Testing Checklist

- [ ] Authentication modal appears on load
- [ ] Dark gradient background with logo visible
- [ ] Password validation works (try wrong password)
- [ ] Modal disappears on successful login
- [ ] Health indicator shows connected
- [ ] Resizable panels work (drag handle)
- [ ] Panel width persists after refresh
- [ ] Direct session loading via URL parameter works
- [ ] JSON visualization is collapsible (tool calls, metadata)
- [ ] Expand All / Collapse All buttons work
- [ ] Can add/remove dynamic filters
- [ ] Search returns results
- [ ] Pagination works
- [ ] Session detail loads
- [ ] Timeline renders correctly
- [ ] Tool calls display with collapsible JSON
- [ ] Feedbacks display in timeline
- [ ] Markdown renders in messages
- [ ] Metrics display correctly
- [ ] Mobile responsive
- [ ] Favicon visible in browser tab

### Test with cURL

```bash
# Test backend connection
curl http://localhost:8882/health

# Test search
curl "http://localhost:8882/api/v1/sessions/search?limit=5"
```

## Troubleshooting

### Frontend Won't Load

1. Check HTTP server is running on port 8883
2. Try accessing http://127.0.0.1:8883
3. Check for port conflicts: `lsof -i :8883`

### Can't Connect to Backend

1. Verify backend is running: `curl http://localhost:8882/health`
2. Check CORS configuration in backend
3. Verify API endpoint URL in `viewer.js`

### Search Returns Empty

1. Check backend database has sessions
2. Verify search filters are correct
3. Check browser console for errors

### Timeline Not Rendering

1. Check session has messages
2. Verify timeline data structure
3. Check browser console for errors

## Future Enhancements

- [ ] Export session to JSON/PDF
- [ ] Search within messages
- [ ] Filter by agent type
- [ ] Real-time updates (WebSocket)
- [ ] Dark mode toggle
- [ ] Save filter presets
- [ ] Advanced date picker
- [ ] Keyboard shortcuts
- [ ] Session comparison
- [ ] Analytics dashboard

## Support

For issues or questions:
- Check backend README for API documentation
- Review browser console for errors
- Check backend logs for server errors

## License

Same as parent MongoDB Session Manager project.
