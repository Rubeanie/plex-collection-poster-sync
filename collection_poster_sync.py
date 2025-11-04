import os
import re
import json
import logging
import hashlib
import time
import sys
import platform
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import local

__version__ = "1.0.2"

# Set plexapi environment variables BEFORE importing plexapi
if "PLEXAPI_HEADER_IDENTIFIER" not in os.environ:
    os.environ["PLEXAPI_HEADER_IDENTIFIER"] = "plex-collection-poster-sync"
if "PLEXAPI_HEADER_DEVICE_NAME" not in os.environ:
    os.environ["PLEXAPI_HEADER_DEVICE_NAME"] = "Collection Poster Sync"
if "PLEXAPI_HEADER_DEVICE" not in os.environ:
    os.environ["PLEXAPI_HEADER_DEVICE"] = "Docker"
if "PLEXAPI_HEADER_PRODUCT" not in os.environ:
    os.environ["PLEXAPI_HEADER_PRODUCT"] = "Plex Collection Poster Sync"
if "PLEXAPI_HEADER_PLATFORM" not in os.environ:
    detected_platform = platform.system()
    os.environ["PLEXAPI_HEADER_PLATFORM"] = detected_platform

from plexapi.server import PlexServer


class CollectionPosterSync:
    """
    Sync collection posters from a folder of images to Plex collections.
    """

    def __init__(self):
        """
        Initialize the sync script with environment variables.
        """
        # Get configuration from environment variables
        self.PLEX_URL = os.getenv("PLEX_URL", "").rstrip("/")
        self.PLEX_TOKEN = os.getenv("PLEX_TOKEN", "")
        self.POSTER_FOLDER = os.getenv("POSTER_FOLDER", "/posters")
        self.REAPPLY_POSTERS = os.getenv("REAPPLY_POSTERS", "false").lower() == "true"
        self.NORMALIZE_HYPHENS = (
            os.getenv("NORMALIZE_HYPHENS", "true").lower() == "true"
        )
        self.REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "30"))
        self.MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
        self.MAX_WORKERS = int(os.getenv("MAX_WORKERS", "4"))  # Thread pool size

        # Supported image formats
        self.IMAGE_EXTENSIONS = [".jpg", ".jpeg", ".png", ".tbn"]

        # Cache file path (stored alongside poster folder)
        self.CACHE_FILE = os.path.join(self.POSTER_FOLDER, ".poster_cache.json")

        # Setup requests session with retry strategy and connection pooling
        self.session = requests.Session()
        retry_strategy = Retry(
            total=self.MAX_RETRIES,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
        )
        # Tune connection pool for better performance with threading
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=20,
            pool_maxsize=20,
        )
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        # Thread-local storage for per-thread sessions
        self._tls = local()

        # Setup logging with custom formatter
        class PrefixFormatter(logging.Formatter):
            """Custom formatter that adds prefix tags like [INF], [DBG], [WRN], [SUC]"""

            def format(self, record):
                # Map log levels to prefixes
                prefix_map = {
                    logging.DEBUG: "[DBG]",
                    logging.INFO: "[INF]",
                    logging.WARNING: "[WRN]",
                    logging.ERROR: "[ERR]",
                    logging.CRITICAL: "[CRI]",
                }
                prefix = prefix_map.get(record.levelno, "[INF]")

                # Check if message starts with [SUC] for success messages
                if (
                    hasattr(record, "msg")
                    and isinstance(record.msg, str)
                    and record.msg.startswith("[SUC]")
                ):
                    prefix = "[SUC]"
                    record.msg = record.msg[5:].strip()  # Remove [SUC] from message

                # Override levelname to include prefix
                record.levelname = prefix
                return super().format(record)

        # Get log level from environment variable (default: INFO)
        log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
        log_level_map = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
            "CRITICAL": logging.CRITICAL,
        }
        log_level = log_level_map.get(log_level_str, logging.INFO)

        # Create logger
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)  # Logger itself handles all levels

        # Remove existing handlers
        self.logger.handlers = []

        # Console handler (stdout) - default to INFO level, can be overridden by LOG_LEVEL
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(
            log_level
        )  # Only show messages at this level and above
        console_formatter = PrefixFormatter("%(levelname)s %(message)s")
        console_handler.setFormatter(console_formatter)
        self.logger.addHandler(console_handler)

        # File handler - optional, only if LOG_PATH is set (always DEBUG for file)
        log_path = os.getenv("LOG_PATH")
        if log_path:
            file_handler = logging.FileHandler(log_path, encoding="utf-8")
            file_handler.setLevel(logging.DEBUG)  # File always gets all logs
            file_formatter = logging.Formatter(
                "%(asctime)s - %(levelname)s - %(message)s"
            )
            file_handler.setFormatter(file_formatter)
            self.logger.addHandler(file_handler)

        self.logger.info("Starting collection poster sync script.")

        # Validate required configuration
        if not self.PLEX_URL or not self.PLEX_TOKEN:
            self.logger.error("PLEX_URL and PLEX_TOKEN must be set")
            raise ValueError("PLEX_URL and PLEX_TOKEN must be set")

        # Connect to Plex
        try:
            self.logger.info(f"Connecting to Plex server at {self.PLEX_URL}")
            self.logger.debug(
                f"Using client identifier: {os.environ.get('PLEXAPI_HEADER_IDENTIFIER')}"
            )

            # Also set headers on our session as a fallback
            plex_headers = {
                "X-Plex-Client-Identifier": os.environ["PLEXAPI_HEADER_IDENTIFIER"],
                "X-Plex-Product": os.environ["PLEXAPI_HEADER_PRODUCT"],
                "X-Plex-Version": __version__,
                "X-Plex-Device": os.environ["PLEXAPI_HEADER_DEVICE"],
                "X-Plex-Device-Name": os.environ["PLEXAPI_HEADER_DEVICE_NAME"],
                "X-Plex-Platform": os.environ["PLEXAPI_HEADER_PLATFORM"],
            }

            self.session.headers.update(plex_headers)

            # Create PlexServer - plexapi will use the stable headers from env vars (set at module level)
            self.PLEX = PlexServer(self.PLEX_URL, self.PLEX_TOKEN, session=self.session)

            # Ensure the PlexServer's session also has our headers
            if hasattr(self.PLEX, "_session") and self.PLEX._session:
                self.PLEX._session.headers.update(plex_headers)

            # Also check for http_session which some versions of plexapi use
            if hasattr(self.PLEX, "http_session") and self.PLEX.http_session:
                self.PLEX.http_session.headers.update(plex_headers)

            # Log the identifier being used for debugging
            actual_identifier = (
                self.PLEX._session.headers.get("X-Plex-Client-Identifier")
                if hasattr(self.PLEX, "_session")
                else plex_headers["X-Plex-Client-Identifier"]
            )
            self.logger.debug(f"Connected with client identifier: {actual_identifier}")

            self.logger.info(f"Successfully connected to Plex server")
        except Exception as e:
            self.logger.error(f"Failed to connect to Plex: {e}")
            raise

    def normalize_collection_name(self, name):
        """
        Normalize collection name for matching.
        Case-insensitive matching. Optionally treats "-" and " " (spaces) as equivalent.

        Args:
            name: Collection name to normalize

        Returns:
            Normalized name (lowercase, optionally with spaces and dashes normalized)
        """
        # Convert to lowercase and strip whitespace
        normalized = name.lower().strip()

        # If NORMALIZE_HYPHENS is enabled, treat hyphens and spaces as equivalent
        if self.NORMALIZE_HYPHENS:
            # Replace both spaces and dashes with a single space
            normalized = re.sub(r"[\s\-]+", " ", normalized)
        else:
            # Only normalize multiple spaces/dashes separately, but don't convert hyphens to spaces
            normalized = re.sub(
                r"\s+", " ", normalized
            )  # Multiple spaces -> single space
            normalized = re.sub(
                r"-+", "-", normalized
            )  # Multiple dashes -> single dash

        return normalized

    def get_image_files(self):
        """
        Get all image files from the poster folder using os.scandir for better performance.

        Returns:
            List of tuples (filename, full_path, collection_name)
        """
        image_files = []

        if not os.path.exists(self.POSTER_FOLDER):
            self.logger.warning(f"Poster folder does not exist: {self.POSTER_FOLDER}")
            return image_files

        try:
            with os.scandir(self.POSTER_FOLDER) as it:
                for entry in it:
                    # Skip directories and non-files
                    if not entry.is_file():
                        continue

                    # Check if file has supported extension
                    _, ext = os.path.splitext(entry.name)
                    if ext.lower() in self.IMAGE_EXTENSIONS:
                        # Extract collection name from filename (without extension)
                        collection_name = os.path.splitext(entry.name)[0]
                        image_files.append((entry.name, entry.path, collection_name))
                        self.logger.debug(
                            f"Found image file: {entry.name} -> collection name: '{collection_name}'"
                        )

        except Exception as e:
            self.logger.error(f"Error reading poster folder: {e}")

        return image_files

    def index_collections(self):
        """
        Build a collection index once for O(1) lookups.
        Maps normalized collection names to (collection, library_title, library_key) tuples.

        Returns:
            Dictionary mapping normalized_name -> (collection, library_title, library_key)
        """
        self.logger.info("Building collection index...")
        collection_index = {}

        try:
            libraries = self.PLEX.library.sections()
            total_collections = 0

            for library in libraries:
                try:
                    collections = library.collections()
                    for collection in collections:
                        normalized_name = self.normalize_collection_name(
                            collection.title
                        )
                        collection_index[normalized_name] = (
                            collection,
                            library.title,
                            library.key,
                        )
                        total_collections += 1

                except Exception as e:
                    self.logger.warning(
                        f"Error accessing collections in library {library.title}: {e}"
                    )
                    continue

            self.logger.info(
                f"Indexed {total_collections} collection(s) across {len(libraries)} library/libraries"
            )

        except Exception as e:
            self.logger.error(f"Error building collection index: {e}")

        return collection_index

    def find_collection_by_name(self, target_name, collection_index):
        """
        Find a Plex collection by normalized name using the pre-built index.

        Args:
            target_name: The collection name to find
            collection_index: Pre-built collection index dictionary

        Returns:
            Tuple of (Collection object, library_title, library_key) if found, (None, None, None) otherwise
        """
        normalized_target = self.normalize_collection_name(target_name)
        result = collection_index.get(normalized_target)

        if result:
            collection, library_title, library_key = result
            self.logger.debug(
                f"Found collection '{collection.title}' (ratingKey {collection.ratingKey}) in library '{library_title}' (section {library_key})"
            )
            return collection, library_title, library_key

        return None, None, None

    def get_current_poster_key(self, collection):
        """
        Get the key of the currently selected poster for a collection.

        Args:
            collection: Plex collection object

        Returns:
            Poster key if found, None otherwise
        """
        try:
            posters = collection.posters()
            for poster in posters:
                if poster.selected:
                    return poster.key
        except Exception as e:
            self.logger.warning(
                f"Error getting current poster for collection {collection.title}: {e}"
            )

        return None

    def calculate_file_hash(self, file_path):
        """
        Calculate SHA256 hash of a file using optimized chunk size.

        Args:
            file_path: Path to the file

        Returns:
            Hex digest of the file hash, or None if error
        """
        try:
            self.logger.debug(f"Calculating hash for file: {file_path}")
            hash_sha256 = hashlib.sha256()
            # Use 128 KB chunks for better performance
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(131072), b""):  # 128 KiB
                    hash_sha256.update(chunk)
            file_hash = hash_sha256.hexdigest()
            self.logger.debug(f"File hash: {file_hash[:16]}...")
            return file_hash
        except Exception as e:
            self.logger.warning(f"Error calculating hash for {file_path}: {e}")
            return None

    def get_thread_session(self):
        """
        Get a thread-local requests session for parallel operations.

        Returns:
            requests.Session instance
        """
        if not hasattr(self._tls, "session"):
            session = requests.Session()
            retry_strategy = Retry(
                total=self.MAX_RETRIES,
                backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["GET", "POST"],
            )
            adapter = HTTPAdapter(
                max_retries=retry_strategy,
                pool_connections=20,
                pool_maxsize=20,
            )
            session.mount("http://", adapter)
            session.mount("https://", adapter)
            # Copy headers from main session
            session.headers.update(self.session.headers)
            self._tls.session = session
        return self._tls.session

    def load_poster_cache(self):
        """
        Load poster state cache from JSON file.

        Returns:
            Dictionary mapping ratingKey -> {"local_hash": str, "poster_key": str}
        """
        if not os.path.exists(self.CACHE_FILE):
            return {}

        try:
            with open(self.CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
                self.logger.debug(f"Loaded cache for {len(cache)} collection(s)")
                return cache
        except Exception as e:
            self.logger.warning(f"Error loading cache file: {e}")
            return {}

    def save_poster_cache(self, cache):
        """
        Save poster state cache to JSON file.

        Args:
            cache: Dictionary mapping ratingKey -> {"local_hash": str, "poster_key": str}
        """
        try:
            # Ensure poster folder exists
            os.makedirs(os.path.dirname(self.CACHE_FILE), exist_ok=True)
            with open(self.CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache, f, indent=2)
            self.logger.debug(f"Saved cache for {len(cache)} collection(s)")
        except Exception as e:
            self.logger.warning(f"Error saving cache file: {e}")

    def get_current_poster_hash(self, collection, session=None):
        """
        Download the current poster and calculate its hash.
        Uses thread-local session if provided for parallel operations.

        Args:
            collection: Plex collection object
            session: Optional requests.Session to use (for threading)

        Returns:
            Tuple of (hash, poster_key) if found, (None, None) otherwise
        """
        if session is None:
            session = self.session

        try:
            poster_key = self.get_current_poster_key(collection)
            if not poster_key:
                self.logger.debug(
                    f"No current poster found for collection '{collection.title}'"
                )
                return None, None

            self.logger.debug(
                f"Downloading current poster for '{collection.title}' (key: {poster_key})"
            )
            # Build full URL for the poster
            poster_url = self.PLEX.url(poster_key)
            headers = {"X-Plex-Token": self.PLEX_TOKEN}

            # Download poster with retry logic
            response = session.get(
                poster_url, headers=headers, timeout=self.REQUEST_TIMEOUT
            )
            if response.status_code == 200:
                # Calculate hash of downloaded content
                hash_sha256 = hashlib.sha256(response.content).hexdigest()
                self.logger.debug(
                    f"Current poster hash for '{collection.title}': {hash_sha256[:16]}..."
                )
                return hash_sha256, poster_key
            else:
                self.logger.warning(
                    f"Failed to download poster (status {response.status_code}) for '{collection.title}'"
                )
        except Exception as e:
            self.logger.debug(
                f"Error getting current poster hash for '{collection.title}': {e}"
            )

        return None, None

    def upload_poster(self, collection, image_path):
        """
        Upload a poster image to a Plex collection with retry logic.

        Args:
            collection: Plex collection object
            image_path: Path to the image file

        Returns:
            True if successful, False otherwise
        """
        # Verify file exists before attempting upload
        if not os.path.exists(image_path):
            self.logger.error(f"Image file does not exist: {image_path}")
            return False

        # Retry upload on failure
        for attempt in range(self.MAX_RETRIES):
            try:
                self.logger.debug(
                    f"Uploading poster for collection '{collection.title}' (attempt {attempt + 1}/{self.MAX_RETRIES})"
                )
                collection.uploadPoster(filepath=image_path)
                self.logger.info(
                    f"[SUC] Successfully uploaded poster for collection '{collection.title}'"
                )
                return True
            except Exception as e:
                if attempt < self.MAX_RETRIES - 1:
                    wait_time = 2**attempt  # Exponential backoff
                    self.logger.warning(
                        f"Upload attempt {attempt + 1} failed for '{collection.title}', retrying in {wait_time}s: {e}"
                    )
                    time.sleep(wait_time)
                else:
                    self.logger.error(
                        f"Error uploading poster for collection '{collection.title}' after {self.MAX_RETRIES} attempts: {e}"
                    )
                    return False

        return False

    def process_image_file(
        self, filename, image_path, collection_name, collection_index, cache
    ):
        """
        Process a single image file (designed for parallel execution).

        Args:
            filename: Name of the image file
            image_path: Full path to the image file
            collection_name: Expected collection name (from filename)
            collection_index: Pre-built collection index
            cache: Poster state cache dictionary

        Returns:
            Tuple of (status, collection_rating_key, new_poster_key, local_hash)
            where status is 'updated', 'skipped', or 'not_found'
        """
        self.logger.info("")
        self.logger.info(f"Processing: {filename} -> collection: '{collection_name}'")

        # Find collection in Plex using index
        collection, library_title, library_key = self.find_collection_by_name(
            collection_name, collection_index
        )

        if not collection:
            self.logger.warning(f"Collection not found for image: {filename}")
            return ("not_found", None, None, None)

        # Log collection found with library info
        if library_title and library_key:
            self.logger.info(
                f"Found collection '{collection.title}' (ratingKey {collection.ratingKey}) in library '{library_title}' (section {library_key})"
            )
        else:
            self.logger.info(
                f"Found collection '{collection.title}' (ratingKey {collection.ratingKey})"
            )

        rating_key = str(collection.ratingKey)

        # Check if we need to update the poster
        should_update = True
        new_poster_key = None
        local_hash = None

        if not self.REAPPLY_POSTERS:
            # Calculate hash of the image we want to upload
            self.logger.debug(
                "Comparing poster hashes to determine if update is needed"
            )
            local_hash = self.calculate_file_hash(image_path)

            if local_hash:
                # Check cache first
                cached = cache.get(rating_key)
                current_poster_key = self.get_current_poster_key(collection)

                if cached and cached.get("local_hash") == local_hash:
                    # Local file hasn't changed - check if Plex poster_key matches
                    if current_poster_key == cached.get("poster_key"):
                        # Both local file and Plex poster are unchanged
                        self.logger.info(
                            f"Poster for collection '{collection.title}' is already set to this image (cache hit), skipping"
                        )
                        should_update = False
                    else:
                        # Plex poster was changed externally - need to verify
                        self.logger.debug(
                            f"Plex poster changed (key mismatch), verifying..."
                        )
                        # Get thread-local session for parallel operations
                        thread_session = self.get_thread_session()
                        current_poster_hash, _ = self.get_current_poster_hash(
                            collection, session=thread_session
                        )
                        if current_poster_hash == local_hash:
                            # Actually matches, just poster_key changed (Plex internal change)
                            self.logger.info(
                                f"Poster for collection '{collection.title}' matches (poster_key changed), skipping"
                            )
                            should_update = False
                            # Update cache with new poster_key
                            cache[rating_key] = {
                                "local_hash": local_hash,
                                "poster_key": current_poster_key,
                            }
                        else:
                            # Posters differ, need update
                            self.logger.debug("Poster hashes differ - update needed")
                elif current_poster_key:
                    # Cache miss or local file changed - check current poster
                    # Get thread-local session for parallel operations
                    thread_session = self.get_thread_session()
                    current_poster_hash, _ = self.get_current_poster_hash(
                        collection, session=thread_session
                    )
                    if current_poster_hash == local_hash:
                        # Hashes match, skip update
                        self.logger.info(
                            f"Poster for collection '{collection.title}' is already set to this image, skipping"
                        )
                        should_update = False
                        # Update cache
                        cache[rating_key] = {
                            "local_hash": local_hash,
                            "poster_key": current_poster_key,
                        }
                    else:
                        self.logger.debug("Poster hashes differ - update needed")
                else:
                    self.logger.debug("No current poster found - update needed")
            else:
                self.logger.debug("Failed to calculate local hash - update needed")
        else:
            self.logger.debug("REAPPLY_POSTERS is enabled - forcing update")

        # Upload the poster if needed
        if should_update:
            if self.upload_poster(collection, image_path):
                # Update cache after successful upload
                if local_hash:
                    new_poster_key = self.get_current_poster_key(collection)
                    cache[rating_key] = {
                        "local_hash": local_hash,
                        "poster_key": new_poster_key or "",
                    }
                return ("updated", rating_key, new_poster_key, local_hash)
            else:
                return ("skipped", rating_key, None, local_hash)
        else:
            return ("skipped", rating_key, None, local_hash)

    def sync_posters(self):
        """
        Main sync function: scan folder, find collections, and update posters.
        Uses collection index and parallel processing for better performance.
        """
        self.logger.info("Starting poster sync process")
        self.logger.info(f"Poster folder: {self.POSTER_FOLDER}")
        self.logger.info(f"REAPPLY_POSTERS: {self.REAPPLY_POSTERS}")
        if self.REAPPLY_POSTERS:
            self.logger.info(
                "Reapply posters is enabled. Posters will be reapplied for all collections."
            )
        self.logger.info(f"NORMALIZE_HYPHENS: {self.NORMALIZE_HYPHENS}")
        self.logger.info(
            f"Using {self.MAX_WORKERS} worker thread(s) for parallel processing"
        )

        # Build collection index once
        collection_index = self.index_collections()

        # Load poster state cache
        cache = self.load_poster_cache()

        # Get all image files
        self.logger.info(f"Scanning poster folder: {self.POSTER_FOLDER}")
        image_files = self.get_image_files()

        if not image_files:
            self.logger.warning("No image files found in poster folder")
            return

        self.logger.info(f"Found {len(image_files)} image file(s)")

        updated_count = 0
        skipped_count = 0
        not_found_count = 0

        # Process image files in parallel using thread pool
        with ThreadPoolExecutor(max_workers=self.MAX_WORKERS) as executor:
            # Submit all tasks
            future_to_file = {
                executor.submit(
                    self.process_image_file,
                    filename,
                    image_path,
                    collection_name,
                    collection_index,
                    cache,
                ): (filename, image_path, collection_name)
                for filename, image_path, collection_name in image_files
            }

            # Process completed tasks
            for future in as_completed(future_to_file):
                filename, image_path, collection_name = future_to_file[future]
                try:
                    status, rating_key, poster_key, local_hash = future.result()
                    if status == "updated":
                        updated_count += 1
                    elif status == "skipped":
                        skipped_count += 1
                    elif status == "not_found":
                        not_found_count += 1
                except Exception as e:
                    self.logger.error(
                        f"Error processing {filename}: {e}", exc_info=True
                    )
                    skipped_count += 1

        # Save updated cache
        self.save_poster_cache(cache)

        # Summary
        self.logger.info("")
        self.logger.info(f"[SUC] Poster sync completed")
        self.logger.info(
            f"Summary: Updated: {updated_count}, Skipped: {skipped_count}, Not found: {not_found_count}"
        )


if __name__ == "__main__":
    sync = None
    try:
        sync = CollectionPosterSync()
        sync.sync_posters()
    except Exception as e:
        # Try to use the logger if sync object was created
        if sync is not None and hasattr(sync, "logger"):
            sync.logger.error(f"Fatal error: {e}")
        else:
            # Fallback if we can't create the sync object
            print(f"[ERR] Fatal error: {e}", file=sys.stderr)
        raise
