import os
import re
import logging
import hashlib
import time
import sys
import platform
import requests
from plexapi.server import PlexServer
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

__version__ = "1.0.2"


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

        # Supported image formats
        self.IMAGE_EXTENSIONS = [".jpg", ".jpeg", ".png", ".tbn"]

        # Setup requests session with retry strategy
        self.session = requests.Session()
        retry_strategy = Retry(
            total=self.MAX_RETRIES,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

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
            # Use a consistent client identifier to avoid "new device" notifications
            # This is the MOST IMPORTANT header - it must be consistent across container restarts
            # If not set, Plex will generate a new device ID based on container metadata, causing notifications
            client_identifier = os.getenv(
                "PLEX_CLIENT_IDENTIFIER", "plex-collection-poster-sync"
            )

            # Auto-detect platform (Linux, Windows, Darwin, etc.)
            # This ensures consistent platform identification without manual configuration
            detected_platform = platform.system()
            # Normalize platform name to match Plex conventions (Linux is most common in containers)
            platform_name = os.getenv("PLEX_PLATFORM", detected_platform)
            
            # Device name - defaults to a descriptive name, can be customized
            device_name = os.getenv("PLEX_DEVICE_NAME", "Plex Collection Poster Sync")

            # Set all device identification headers required by Plex
            # These headers ensure Plex recognizes this as the same device across container restarts
            plex_headers = {
                "X-Plex-Client-Identifier": client_identifier,  # CRITICAL: Must be consistent
                    "X-Plex-Product": "Plex Collection Poster Sync",
                    "X-Plex-Version": __version__,
                "X-Plex-Device": device_name,
                "X-Plex-Platform": platform_name,  # Auto-detected, can be overridden
                }
            
            self.session.headers.update(plex_headers)

            # Create PlexServer with our configured session
            # Note: plexapi may create its own session, but we'll try to use ours
            self.PLEX = PlexServer(self.PLEX_URL, self.PLEX_TOKEN, session=self.session)

            # Ensure the PlexServer's session also has our headers
            # This is critical because plexapi may use its own session internally
            if hasattr(self.PLEX, "_session") and self.PLEX._session:
                self.PLEX._session.headers.update(plex_headers)
            
            # Also check for http_session which some versions of plexapi use
            if hasattr(self.PLEX, "http_session") and self.PLEX.http_session:
                self.PLEX.http_session.headers.update(plex_headers)

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
        Get all image files from the poster folder.

        Returns:
            List of tuples (filename, full_path, collection_name)
        """
        image_files = []

        if not os.path.exists(self.POSTER_FOLDER):
            self.logger.warning(f"Poster folder does not exist: {self.POSTER_FOLDER}")
            return image_files

        try:
            for filename in os.listdir(self.POSTER_FOLDER):
                file_path = os.path.join(self.POSTER_FOLDER, filename)

                # Skip directories
                if os.path.isdir(file_path):
                    continue

                # Check if file has supported extension
                _, ext = os.path.splitext(filename)
                if ext.lower() in self.IMAGE_EXTENSIONS:
                    # Verify file exists and is readable
                    if not os.path.isfile(file_path):
                        self.logger.warning(f"Skipping non-file: {file_path}")
                        continue

                    # Extract collection name from filename (without extension)
                    collection_name = os.path.splitext(filename)[0]
                    image_files.append((filename, file_path, collection_name))
                    self.logger.debug(
                        f"Found image file: {filename} -> collection name: '{collection_name}'"
                    )

        except Exception as e:
            self.logger.error(f"Error reading poster folder: {e}")

        return image_files

    def find_collection_by_name(self, target_name):
        """
        Find a Plex collection by normalized name.
        Searches across all libraries.

        Args:
            target_name: The normalized collection name to find

        Returns:
            Tuple of (Collection object, library_title, library_key) if found, (None, None, None) otherwise
        """
        normalized_target = self.normalize_collection_name(target_name)

        try:
            # Get all libraries
            libraries = self.PLEX.library.sections()

            for library in libraries:
                try:
                    # Get all collections in this library
                    collections = library.collections()

                    for collection in collections:
                        collection_normalized = self.normalize_collection_name(
                            collection.title
                        )

                        if collection_normalized == normalized_target:
                            self.logger.debug(
                                f"Found collection '{collection.title}' (ratingKey {collection.ratingKey}) in library '{library.title}' (section {library.key})"
                            )
                            return collection, library.title, library.key

                except Exception as e:
                    self.logger.warning(
                        f"Error accessing collections in library {library.title}: {e}"
                    )
                    continue

        except Exception as e:
            self.logger.error(f"Error searching for collection: {e}")

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
        Calculate SHA256 hash of a file.

        Args:
            file_path: Path to the file

        Returns:
            Hex digest of the file hash, or None if error
        """
        try:
            self.logger.debug(f"Calculating hash for file: {file_path}")
            hash_sha256 = hashlib.sha256()
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_sha256.update(chunk)
            file_hash = hash_sha256.hexdigest()
            self.logger.debug(f"File hash: {file_hash[:16]}...")
            return file_hash
        except Exception as e:
            self.logger.warning(f"Error calculating hash for {file_path}: {e}")
            return None

    def get_current_poster_hash(self, collection):
        """
        Download the current poster and calculate its hash.

        Args:
            collection: Plex collection object

        Returns:
            Hash of current poster, or None if error or no poster
        """
        try:
            poster_key = self.get_current_poster_key(collection)
            if not poster_key:
                self.logger.debug(
                    f"No current poster found for collection '{collection.title}'"
                )
                return None

            self.logger.debug(
                f"Downloading current poster for '{collection.title}' (key: {poster_key})"
            )
            # Build full URL for the poster
            poster_url = self.PLEX.url(poster_key)
            headers = {"X-Plex-Token": self.PLEX_TOKEN}

            # Download poster with retry logic
            response = self.session.get(
                poster_url, headers=headers, timeout=self.REQUEST_TIMEOUT
            )
            if response.status_code == 200:
                # Calculate hash of downloaded content
                hash_sha256 = hashlib.sha256(response.content).hexdigest()
                self.logger.debug(
                    f"Current poster hash for '{collection.title}': {hash_sha256[:16]}..."
                )
                return hash_sha256
            else:
                self.logger.warning(
                    f"Failed to download poster (status {response.status_code}) for '{collection.title}'"
                )
        except Exception as e:
            self.logger.debug(
                f"Error getting current poster hash for '{collection.title}': {e}"
            )

        return None

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

    def sync_posters(self):
        """
        Main sync function: scan folder, find collections, and update posters.
        """
        self.logger.info("Starting poster sync process")
        self.logger.info(f"Poster folder: {self.POSTER_FOLDER}")
        self.logger.info(f"REAPPLY_POSTERS: {self.REAPPLY_POSTERS}")
        if self.REAPPLY_POSTERS:
            self.logger.info(
                "Reapply posters is enabled. Posters will be reapplied for all collections."
            )
        self.logger.info(f"NORMALIZE_HYPHENS: {self.NORMALIZE_HYPHENS}")

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

        # Process each image file
        for filename, image_path, collection_name in image_files:
            self.logger.info("")
            self.logger.info(
                f"Processing: {filename} -> collection: '{collection_name}'"
            )

            # Find collection in Plex
            self.logger.debug(
                f"Searching for collection with name: '{collection_name}'"
            )
            collection, library_title, library_key = self.find_collection_by_name(
                collection_name
            )

            if not collection:
                self.logger.warning(f"Collection not found for image: {filename}")
                not_found_count += 1
                continue

            # Log collection found with library info
            if library_title and library_key:
                self.logger.info(
                    f"Found collection '{collection.title}' (ratingKey {collection.ratingKey}) in library '{library_title}' (section {library_key})"
                )
            else:
                self.logger.info(
                    f"Found collection '{collection.title}' (ratingKey {collection.ratingKey})"
                )

            # Check if we need to update the poster
            should_update = True

            if not self.REAPPLY_POSTERS:
                # Calculate hash of the image we want to upload
                self.logger.debug(
                    "Comparing poster hashes to determine if update is needed"
                )
                new_image_hash = self.calculate_file_hash(image_path)

                if new_image_hash:
                    # Get hash of current poster
                    current_poster_hash = self.get_current_poster_hash(collection)

                    # If hashes match, skip update
                    if current_poster_hash and current_poster_hash == new_image_hash:
                        self.logger.info(
                            f"Poster for collection '{collection.title}' is already set to this image, skipping"
                        )
                        should_update = False
                        skipped_count += 1
                    elif current_poster_hash:
                        self.logger.debug(f"Poster hashes differ - update needed")
                    else:
                        self.logger.debug(f"No current poster found - update needed")
            else:
                self.logger.debug("REAPPLY_POSTERS is enabled - forcing update")

            # Upload the poster if needed
            if should_update:
                if self.upload_poster(collection, image_path):
                    updated_count += 1
                else:
                    skipped_count += 1

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
