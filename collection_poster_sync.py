import os
import re
import logging
import hashlib
import time
import requests
from plexapi.server import PlexServer
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


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
        self.NORMALIZE_HYPHENS = os.getenv("NORMALIZE_HYPHENS", "true").lower() == "true"
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

        # Setup logging
        log_path = os.getenv("LOG_PATH", "/app/run.log")
        logging.basicConfig(
            filename=log_path,
            encoding="utf-8",
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
        )
        self.logger = logging.getLogger(__name__)
        self.logger.info("Starting collection poster sync script.")

        # Validate required configuration
        if not self.PLEX_URL or not self.PLEX_TOKEN:
            self.logger.error("PLEX_URL and PLEX_TOKEN must be set")
            raise ValueError("PLEX_URL and PLEX_TOKEN must be set")

        # Connect to Plex
        try:
            self.PLEX = PlexServer(self.PLEX_URL, self.PLEX_TOKEN)
            self.logger.info(f"Connected to Plex server at {self.PLEX_URL}")
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
            normalized = re.sub(r"\s+", " ", normalized)  # Multiple spaces -> single space
            normalized = re.sub(r"-+", "-", normalized)  # Multiple dashes -> single dash
        
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
                        f"Found image: {filename} -> collection: {collection_name}"
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
            Collection object if found, None otherwise
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
                                f'Found collection "{collection.title}" in library "{library.title}"'
                            )
                            return collection

                except Exception as e:
                    self.logger.warning(
                        f"Error accessing collections in library {library.title}: {e}"
                    )
                    continue

        except Exception as e:
            self.logger.error(f"Error searching for collection: {e}")

        return None

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
            hash_sha256 = hashlib.sha256()
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_sha256.update(chunk)
            return hash_sha256.hexdigest()
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
                return None

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
                return hash_sha256
        except Exception as e:
            self.logger.debug(
                f"Error getting current poster hash for {collection.title}: {e}"
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
                collection.uploadPoster(filepath=image_path)
                self.logger.info(
                    f'Successfully uploaded poster for collection "{collection.title}"'
                )
                return True
            except Exception as e:
                if attempt < self.MAX_RETRIES - 1:
                    wait_time = 2**attempt  # Exponential backoff
                    self.logger.warning(
                        f'Upload attempt {attempt + 1} failed for "{collection.title}", retrying in {wait_time}s: {e}'
                    )
                    time.sleep(wait_time)
                else:
                    self.logger.error(
                        f'Error uploading poster for collection "{collection.title}" after {self.MAX_RETRIES} attempts: {e}'
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
        self.logger.info(f"NORMALIZE_HYPHENS: {self.NORMALIZE_HYPHENS}")

        # Get all image files
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
            self.logger.info(
                f'Processing: {filename} -> collection: "{collection_name}"'
            )

            # Find collection in Plex
            collection = self.find_collection_by_name(collection_name)

            if not collection:
                self.logger.warning(f"Collection not found for image: {filename}")
                not_found_count += 1
                continue

            # Check if we need to update the poster
            should_update = True

            if not self.REAPPLY_POSTERS:
                # Calculate hash of the image we want to upload
                new_image_hash = self.calculate_file_hash(image_path)

                if new_image_hash:
                    # Get hash of current poster
                    current_poster_hash = self.get_current_poster_hash(collection)

                    # If hashes match, skip update
                    if current_poster_hash and current_poster_hash == new_image_hash:
                        self.logger.info(
                            f'Poster for collection "{collection.title}" is already set to this image, skipping'
                        )
                        should_update = False
                        skipped_count += 1

            # Upload the poster if needed
            if should_update:
                if self.upload_poster(collection, image_path):
                    updated_count += 1
                else:
                    skipped_count += 1

        # Summary
        self.logger.info("Poster sync completed")
        self.logger.info(
            f"Updated: {updated_count}, Skipped: {skipped_count}, Not found: {not_found_count}"
        )


if __name__ == "__main__":
    try:
        sync = CollectionPosterSync()
        sync.sync_posters()
    except Exception as e:
        logging.error(f"Fatal error: {e}")
        raise
