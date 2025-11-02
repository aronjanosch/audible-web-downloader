# AudioBookshelf Naming Structure Implementation Plan

## Overview

This document outlines the plan to implement AudioBookshelf-compatible folder naming and directory structure for downloaded audiobooks.

**Goal:** Enable users to download audiobooks directly into an AudioBookshelf-compatible directory structure for seamless library integration.

---

## Current State

### What We Have
- ✅ **Configurable library paths** - Users can add/manage multiple libraries with custom download locations (stored in `accounts.json`)
- ✅ **Comprehensive Audible metadata** - Full access to all required metadata fields:
  - `title` - Book title
  - `authors` - Array of author objects with `name` field
  - `narrators` - Array of narrator objects with `name` field
  - `series` - Array with `title` and `sequence` fields
  - `release_date` - Publication year (format: "YYYY-MM-DD")
  - `publisher_name`, `asin`, `language`, `runtime_length_min`
- ✅ **Metadata embedding** - Currently embeds metadata in M4B files using MP4 tags

### Current Directory Structure
```
{library_path}/
  └── {sanitized_book_title}/
      ├── {book_title}.m4b
      ├── {book_title}.aaxc
      └── cover.jpg
```

**Location:** `downloader.py:182-190`

---

## AudioBookshelf Requirements

### Required Directory Structure

AudioBookshelf expects: **Author → Series → Title → Audio Files**

#### For Series Books:
```
{library_path}/
  └── Terry Goodkind/                          ← Author folder
      └── Sword of Truth/                      ← Series folder
          └── Vol. 1 - 1994 - Wizards First Rule {Sam Tsoutsouvas}/  ← Title folder
              ├── Wizards First Rule.m4b
              └── cover.jpg
```

#### For Standalone Books:
```
{library_path}/
  └── Steven Levy/                             ← Author folder
      └── 1994 - Hackers {Mike Chamberlain}/   ← Title folder
          └── Hackers.m4b
```

### Title Folder Naming Pattern

AudioBookshelf parses metadata from folder names using this format:

```
[Sequence] - [Year] - [Title] - [Subtitle] {Narrator}
```

**Rules:**
- **Sequence:** `Vol. 1`, `Book 1`, `Volume 1`, `1.`, or just `1` (case-insensitive, decimals supported)
  - If not at the beginning, must be preceded by " - " and "Vol", "Vol.", "Volume", or "Book"
  - Must be followed by " - " or ". "
- **Year:** Must be first part OR directly after sequence, separated by " - " on both sides
- **Subtitle:** Optional, separated by " - " (requires enabling in AudioBookshelf settings)
- **Narrator:** Must be wrapped in curly braces: `{Name}`

**Valid Examples:**
- `Wizards First Rule`
- `1994 - Wizards First Rule`
- `Vol. 1 - 1994 - Wizards First Rule {Sam Tsoutsouvas}`
- `1994 - Book 1 - Wizards First Rule - A Subtitle {Narrator}`
- `(1994) - Wizards First Rule`

### Author Folder Naming

Supports:
- `First Last` (e.g., "Terry Goodkind")
- `Last, First` (e.g., "Goodkind, Terry")
- Multiple authors separated by `,`, `;`, `&`, or `and`

---

## Implementation Plan

### Phase 1: Core Path Builder Function

**File:** `downloader.py`

Create a new function `build_audiobookshelf_path()` that constructs the nested folder structure.

```python
def build_audiobookshelf_path(
    base_path: str,
    title: str,
    authors: List[Dict],
    narrators: List[Dict],
    series: List[Dict] = None,
    release_date: str = None,
    use_audiobookshelf_structure: bool = False
) -> Path:
    """
    Build AudioBookshelf-compatible directory path.

    Returns:
        Path object with structure: base_path/Author/[Series]/Title/
    """
```

**Logic:**

1. **Author Folder:**
   ```python
   # Extract author names from list
   author_names = [author['name'] for author in authors]

   # Join multiple authors
   if len(author_names) > 2:
       author_folder = ", ".join(author_names[:-1]) + " and " + author_names[-1]
   elif len(author_names) == 2:
       author_folder = " & ".join(author_names)
   else:
       author_folder = author_names[0] if author_names else "Unknown Author"

   # Sanitize for filesystem
   author_folder = sanitize_filename(author_folder)
   ```

2. **Series Folder (Optional):**
   ```python
   series_folder = None
   if series and len(series) > 0:
       series_folder = sanitize_filename(series[0]['title'])
   ```

3. **Title Folder:**
   ```python
   title_parts = []

   # Add sequence if in series
   if series and len(series) > 0:
       sequence = series[0].get('sequence')
       if sequence:
           # Format sequence (e.g., "Vol. 1" or "Book 1.5")
           title_parts.append(f"Vol. {sequence}")

   # Add year
   if release_date:
       year = release_date.split('-')[0]  # Extract YYYY from YYYY-MM-DD
       title_parts.append(year)

   # Add title
   title_parts.append(title)

   # Add narrator (optional, in curly braces)
   if narrators and len(narrators) > 0:
       narrator_names = [n['name'] for n in narrators[:2]]  # Limit to first 2
       narrator_str = " & ".join(narrator_names)
       # Add at the end after all other parts
       title_folder = " - ".join(title_parts) + f" {{{narrator_str}}}"
   else:
       title_folder = " - ".join(title_parts)

   title_folder = sanitize_filename(title_folder)
   ```

4. **Construct Path:**
   ```python
   if use_audiobookshelf_structure:
       if series_folder:
           return Path(base_path) / author_folder / series_folder / title_folder
       else:
           return Path(base_path) / author_folder / title_folder
   else:
       # Legacy flat structure
       return Path(base_path) / sanitize_filename(title)
   ```

### Phase 2: Update Download Logic

**File:** `downloader.py` (around lines 182-190)

**Current Code:**
```python
# Create book directory
book_dir = downloads_dir / sanitize_filename(product['title'])
book_dir.mkdir(parents=True, exist_ok=True)
```

**New Code:**
```python
# Build directory path based on user preference
use_abs_structure = self.config.get('use_audiobookshelf_structure', False)

book_dir = build_audiobookshelf_path(
    base_path=str(downloads_dir),
    title=product['title'],
    authors=product.get('authors', []),
    narrators=product.get('narrators', []),
    series=product.get('series'),
    release_date=product.get('release_date'),
    use_audiobookshelf_structure=use_abs_structure
)

book_dir.mkdir(parents=True, exist_ok=True)
```

### Phase 3: Add Configuration Option

#### 3.1 Update Data Model

**File:** `accounts.json` structure

Add new field to library configuration:
```json
{
  "libraries": [
    {
      "name": "My AudioBookshelf Library",
      "path": "/path/to/audiobookshelf",
      "use_audiobookshelf_structure": true  // NEW FIELD
    }
  ]
}
```

#### 3.2 Update UI

**File:** `templates/base.html` (Library Management Section)

Add checkbox in the "Add Library" form:
```html
<div class="form-check mb-3">
    <input class="form-check-input"
           type="checkbox"
           id="useAudiobookshelfStructure"
           checked>
    <label class="form-check-label" for="useAudiobookshelfStructure">
        Use AudioBookshelf naming structure
        <small class="text-muted d-block">
            Organize downloads in Author/Series/Title folders
        </small>
    </label>
</div>
```

Add to existing library display:
```html
<!-- Show current setting -->
<span class="badge bg-info" v-if="library.use_audiobookshelf_structure">
    AudioBookshelf Structure
</span>
```

#### 3.3 Update API Endpoints

**File:** `routes/main.py`

Update library management endpoints:

```python
@main.route('/api/libraries', methods=['POST'])
def add_library():
    data = request.get_json()
    library = {
        'name': data['name'],
        'path': data['path'],
        'use_audiobookshelf_structure': data.get('use_audiobookshelf_structure', True)
    }
    # ... save to accounts.json
```

### Phase 4: Update Library Scanner

**File:** `library_scanner.py`

Update `scan_library()` to support nested structure:

```python
def scan_library(library_path: str) -> List[Dict]:
    """
    Scan library supporting both flat and nested AudioBookshelf structure.

    Supports:
    - Flat: {library_path}/{Title}/{files}
    - Nested: {library_path}/{Author}/{Series}/{Title}/{files}
    - Nested: {library_path}/{Author}/{Title}/{files}
    """
    books = []

    # Walk directory tree
    for root, dirs, files in os.walk(library_path):
        # Look for audio files
        audio_files = [f for f in files if f.endswith(('.m4b', '.mp3', '.m4a'))]

        if audio_files:
            # This is a book folder
            book_data = extract_book_metadata(root, audio_files)

            # Try to extract metadata from folder structure
            path_parts = Path(root).relative_to(library_path).parts

            if len(path_parts) >= 2:
                # Nested structure: extract author, series, title
                book_data['author'] = path_parts[0]
                if len(path_parts) == 3:
                    book_data['series'] = path_parts[1]
                    book_data['title_folder'] = path_parts[2]
                else:
                    book_data['title_folder'] = path_parts[1]

                # Parse title folder for metadata
                parsed = parse_audiobookshelf_title(book_data['title_folder'])
                book_data.update(parsed)

            books.append(book_data)

    return books

def parse_audiobookshelf_title(folder_name: str) -> Dict:
    """
    Parse AudioBookshelf title folder format.

    Example: "Vol. 1 - 1994 - Wizards First Rule {Sam Tsoutsouvas}"
    Returns: {sequence: "1", year: "1994", title: "...", narrator: "..."}
    """
    # Implementation using regex patterns
    pass
```

---

## Edge Cases to Handle

### 1. Missing Metadata
- **No authors:** Use "Unknown Author"
- **No series:** Skip series folder, use Author/Title structure
- **No release date:** Omit year from title folder
- **No narrators:** Omit narrator from title folder

### 2. Filesystem Safety
- **Special characters:** Sanitize all folder names (remove `/`, `\`, `:`, `*`, etc.)
- **Path length limits:** Consider Windows 260-character limit
- **Duplicate names:** Handle multiple books with same title by same author

### 3. Multiple Authors/Narrators
- **Many authors:** Use "Various Authors" if more than 3
- **Multiple narrators:** Include only first 2, separated by " & "

### 4. Series Without Sequence
- If `series.sequence` is `None` or empty, still create series folder but omit sequence from title

### 5. Backward Compatibility
- Existing downloads in flat structure should still be scannable
- Library scanner must support both structures simultaneously

---

## Testing Plan

### Test Cases

#### 1. Series Book with Full Metadata
```python
test_data = {
    'title': 'Wizards First Rule',
    'authors': [{'name': 'Terry Goodkind'}],
    'narrators': [{'name': 'Sam Tsoutsouvas'}],
    'series': [{'title': 'Sword of Truth', 'sequence': '1'}],
    'release_date': '1994-08-15'
}
# Expected: Terry Goodkind/Sword of Truth/Vol. 1 - 1994 - Wizards First Rule {Sam Tsoutsouvas}/
```

#### 2. Standalone Book
```python
test_data = {
    'title': 'Hackers',
    'authors': [{'name': 'Steven Levy'}],
    'narrators': [{'name': 'Mike Chamberlain'}],
    'series': [],
    'release_date': '2010-05-19'
}
# Expected: Steven Levy/2010 - Hackers {Mike Chamberlain}/
```

#### 3. Multiple Authors
```python
test_data = {
    'title': 'The Courage to Be Disliked',
    'authors': [{'name': 'Ichiro Kishimi'}, {'name': 'Fumitake Koga'}],
    'narrators': [{'name': 'Narrator One'}],
    'release_date': '2018-05-08'
}
# Expected: Ichiro Kishimi & Fumitake Koga/2018 - The Courage to Be Disliked {Narrator One}/
```

#### 4. Missing Metadata
```python
test_data = {
    'title': 'Unknown Book',
    'authors': [],
    'narrators': [],
    'series': [],
    'release_date': None
}
# Expected: Unknown Author/Unknown Book/
```

#### 5. Series Without Sequence
```python
test_data = {
    'title': 'Book Title',
    'authors': [{'name': 'Author Name'}],
    'series': [{'title': 'Series Name', 'sequence': None}],
    'release_date': '2020-01-01'
}
# Expected: Author Name/Series Name/2020 - Book Title/
```

#### 6. Special Characters in Names
```python
test_data = {
    'title': 'Book: A Tale of Something/Anything',
    'authors': [{'name': 'Author "Nickname" Name'}],
    'release_date': '2021-06-15'
}
# Expected: Author Nickname Name/2021 - Book A Tale of Something Anything/
```

### Integration Tests

1. **Download Flow Test:**
   - Enable AudioBookshelf structure
   - Download a book
   - Verify folder structure matches expected pattern
   - Verify M4B file exists in correct location

2. **Library Scanner Test:**
   - Create mixed library (flat + nested structure)
   - Run library scan
   - Verify all books are detected
   - Verify metadata is extracted correctly

3. **Comparison Test:**
   - Download same book twice (once flat, once nested)
   - Run library comparison
   - Verify both are detected as same book

---

## File Changes Summary

### New Files
- None (all changes to existing files)

### Modified Files

1. **`downloader.py`**
   - Add `build_audiobookshelf_path()` function
   - Update download path construction (lines ~182-190)
   - Update path references throughout download process

2. **`library_scanner.py`**
   - Update `scan_library()` to support nested structure
   - Add `parse_audiobookshelf_title()` helper function
   - Maintain backward compatibility

3. **`templates/base.html`**
   - Add checkbox in library management UI
   - Display AudioBookshelf structure badge

4. **`routes/main.py`**
   - Update `/api/libraries` POST endpoint
   - Update library data structure handling

5. **`accounts.json`** (data file)
   - Add `use_audiobookshelf_structure` field to library objects

---

## Future Enhancements

### Phase 2 Features (Optional)

1. **Customizable Templates:**
   - Allow users to define custom naming patterns
   - Example: `{author}/{year} - {title} [{narrator}]`

2. **Migration Tool:**
   - Provide tool to reorganize existing flat libraries into nested structure
   - Batch processing with progress indicator

3. **Additional Metadata Parsing:**
   - Extract subtitle from Audible if available
   - Parse multiple series (some books belong to multiple series)

4. **Advanced AudioBookshelf Integration:**
   - Generate `.opf` metadata files
   - Create `desc.txt` and `reader.txt` files
   - Embed cover art in M4B files

5. **Validation Tool:**
   - Verify folder structure matches AudioBookshelf requirements
   - Suggest corrections for non-compliant names

---

## References

- **AudioBookshelf Documentation:** https://www.audiobookshelf.org/docs/#book-directory-structure
- **Audible API Library:** https://github.com/mkb79/Audible
- **Current Implementation:**
  - `downloader.py:182-190` - Current download path logic
  - `library_scanner.py:106-158` - Current scanning logic
  - `auth.py:69-145` - Audible library fetch with metadata

---

## Developer Notes

### Key Considerations

1. **Path Separators:** Always use `pathlib.Path` for cross-platform compatibility
2. **Sanitization:** Reuse existing `sanitize_filename()` function for consistency
3. **Configuration:** Store settings per-library, not globally
4. **Default Behavior:** New libraries should default to AudioBookshelf structure enabled
5. **Testing:** Test on Windows (path length limits) and macOS/Linux (case sensitivity)

### Estimated Effort

- **Phase 1 (Path Builder):** 2-3 hours
- **Phase 2 (Download Logic):** 1-2 hours
- **Phase 3 (UI/Config):** 2-3 hours
- **Phase 4 (Scanner):** 3-4 hours
- **Testing:** 2-3 hours

**Total:** ~10-15 hours of development time

---

## Questions for Product Owner

Before implementation, clarify:

1. Should existing flat downloads be migrated automatically?
2. Default setting for new libraries: AudioBookshelf ON or OFF?
3. Handle subtitle extraction from Audible metadata?
4. Maximum narrator count in folder name (currently planning 2)?
5. Should we generate additional AudioBookshelf metadata files (.opf, desc.txt)?
