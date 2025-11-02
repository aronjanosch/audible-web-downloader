import asyncio
import audible
from pathlib import Path
import json

class AudibleAuth:
    def __init__(self, account_name, region="us"):
        self.account_name = account_name
        self.region = region
        # Store auth files in config/auth/{account_name}/ for better organization
        self.config_dir = Path("config") / "auth" / account_name
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.auth_file = self.config_dir / "auth.json"
    
    async def authenticate(self):
        """Authenticate with Audible using device registration"""
        try:
            # Try to load existing auth
            if self.auth_file.exists():
                auth = audible.Authenticator.from_file(self.auth_file)
                # Test the authentication
                async with audible.AsyncClient(auth=auth) as client:
                    # Try to make a simple API call to verify auth works
                    library = await client.library(num_results=1)
                    return auth
            
            # If no existing auth or it failed, start new authentication
            print("🔐 Starting Audible authentication...")
            print("📋 Authentication Instructions:")
            print("1. Click the authentication link that will appear below")
            print("2. Sign in with your Audible credentials in the new tab")  
            print("3. Complete any verification steps (2FA, CAPTCHA, etc.)")
            print("4. After successful login, you'll see a success page")
            print("5. Return to this page - authentication will complete automatically")
            
            # Map region codes to locale names
            region_map = {
                'us': 'united_states',
                'uk': 'united_kingdom', 
                'de': 'germany',
                'fr': 'france',
                'ca': 'canada',
                'it': 'italy',
                'au': 'australia',
                'in': 'india',
                'jp': 'japan',
                'es': 'spain',
                'br': 'brazil'
            }
            
            locale_name = region_map.get(self.region.lower(), 'united_states')
            locale_template = audible.localization.LOCALE_TEMPLATES[locale_name]
            locale = audible.localization.Locale(**locale_template)
            
            # Use the external browser authentication method
            auth = audible.Authenticator.from_login_external(
                locale=locale,
                with_username=False
            )
            
            # Save the authentication
            auth.to_file(self.auth_file, encryption=False)
            
            return auth
            
        except Exception as e:
            print(f"Authentication failed: {str(e)}")
            return None
    
    async def get_library(self, auth):
        """Fetch the user's Audible library"""
        try:
            async with audible.AsyncClient(auth=auth) as client:
                print("📚 Fetching your Audible library...")
                
                # Fetch library with relevant response groups
                library = await client.get(
                    path="library", 
                    params={
                        "num_results": 1000,  # Get all books
                        "response_groups": "product_desc,product_attrs,media,series,contributors"
                    }
                )
                
                # Extract and format the book data
                books = []
                for item in library.get('items', []):
                    # Extract authors
                    authors = []
                    if 'authors' in item and item['authors']:
                        authors = [author.get('name', '') for author in item['authors']]
                    
                    # Extract narrators
                    narrators = []
                    if 'narrators' in item and item['narrators']:
                        narrators = [narrator.get('name', '') for narrator in item['narrators']]
                    
                    # Extract series info - preserve full structure for downloads
                    series_info = ""
                    series_data = None
                    if 'series' in item and item['series']:
                        series_list = item['series']
                        if series_list:
                            # Keep full series data with sequence for downloads
                            series_data = series_list
                            # Display string for UI
                            series_info = series_list[0].get('title', '')

                    # Extract cover image
                    cover_url = ""
                    if 'product_images' in item and item['product_images']:
                        # Try to get a good resolution image
                        images = item['product_images']
                        cover_url = images.get('500') or images.get('300') or images.get('180') or ""
                    
                    # Extract runtime
                    runtime_mins = item.get('runtime_length_min', 0)

                    # Extract release year from release_date
                    release_date = item.get('release_date', '')
                    release_year = ''
                    if release_date:
                        try:
                            # Release date format is typically "YYYY-MM-DD"
                            release_year = release_date.split('-')[0] if '-' in release_date else release_date[:4]
                        except:
                            release_year = ''

                    book = {
                        'asin': item.get('asin', ''),
                        'title': item.get('title', 'Unknown Title'),
                        'authors': ', '.join(authors) if authors else 'Unknown Author',
                        'narrator': ', '.join(narrators) if narrators else '',
                        'language': item.get('language', 'Unknown'),
                        'length_mins': runtime_mins,
                        'release_date': release_date,
                        'release_year': release_year,
                        'publisher': item.get('publisher_name', ''),
                        'series': series_info,  # String for UI display
                        'series_data': series_data,  # Full list structure with sequence numbers
                        'cover_url': cover_url,
                        'description': item.get('publisher_summary', ''),
                    }
                    books.append(book)
                
                print(f"Loaded {len(books)} books from your library!")
                return books
                                
        except Exception as e:
            print(f"Failed to fetch library: {str(e)}")
            return []
    
    def is_authenticated(self):
        """Check if we have valid authentication"""
        return self.auth_file.exists()
    
    def load_auth(self):
        """Load existing authentication"""
        if self.auth_file.exists():
            return audible.Authenticator.from_file(self.auth_file)
        return None

async def authenticate_account(account_name, region):
    """Helper function to authenticate an account"""
    auth_handler = AudibleAuth(account_name, region)
    return await auth_handler.authenticate()

async def fetch_library(account_name, region):
    """Helper function to fetch library for an account"""
    auth_handler = AudibleAuth(account_name, region)
    auth = auth_handler.load_auth()
    
    if not auth:
        print("No authentication found. Please authenticate first.")
        return []
    
    return await auth_handler.get_library(auth)