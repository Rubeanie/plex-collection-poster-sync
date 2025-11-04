# Plex Collection Poster Sync

A Docker container that automatically syncs collection posters from a folder of images to Plex collections. Perfect for Plex media server users who want to customize their collection artwork. Images are matched to collections by filename (case-insensitive, with flexible matching for spaces and dashes).

### Features

- **Automatic Sync**: Scans a folder for images and matches them to Plex collections
- **Smart Matching**: Case-insensitive collection name matching that treats "-" and spaces as equivalent
- **Duplicate Detection**: Only uploads posters if they differ from the current poster (uses SHA256 hash comparison)
- **Scheduled Execution**: Runs on a configurable CRON schedule
- **Supported Formats**: jpg, jpeg, png, tbn
- **Error Handling**: Retry logic for API calls and robust error handling
- **Logging**: Comprehensive logging with configurable verbosity (INFO by default, DEBUG available)

### Requirements

- Docker
- Plex Media Server
- Plex authentication token

### Usage

1. **Get your Plex token**: [How to find your Plex token](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/)

#### Docker

2. **Build and Run the Container**:

```yaml
version: '3.8'

services:
  collection-poster-sync:
    image: rubeanie/plex-collection-poster-sync:latest
    container_name: collection-poster-sync
    restart: unless-stopped
    # user: "1000:1000" # Set the user/group IDs (default: 1000:1000)
    environment:
      PLEX_URL: "http://localhost:32400" # Plex server URL (e.g., "http://192.168.0.139:32400")
      PLEX_TOKEN: "PLEX TOKEN" # Plex authentication token
      POSTER_FOLDER: "/posters" # Path inside container where images folder is mounted
      CRON_SCHEDULE: "0 */8 * * *" # CRON expression for scheduled runs (every 8 hours by default)
      RUN_ON_CREATION: "true" # Set to "true" to run sync immediately on container startup, set to "false" to wait for CRON schedule
      REAPPLY_POSTERS: "false" # Set to "true" to force update all posters even if unchanged
      NORMALIZE_HYPHENS: "true" # Set to "false" to treat hyphens and spaces as different characters
      TZ: "Australia/Perth" # Replace with your timezone
      # Optional: Advanced configuration options in docker-compose.yml
    volumes:
      - /path/to/your/posters:/posters # Path to your local folder containing poster images
```

3. **Prepare your poster images**:
   - Place image files in the folder you'll mount to `/posters`
   - Name files to match your collection names (e.g., `Leaving Soon.jpg` or `leaving-soon.png`)
   - The script will match filenames (without extension) to collection names
   - **Need help creating posters?** Check the `examples/` folder for:
     - `collection-name.png` - Example poster image showing proper dimensions and styling
     - `Poster Template.fig` - Figma template file for creating custom collection posters

4. Run the container

```yaml
docker-compose up --build
```

### Collection Name Matching

The script uses flexible matching to find collections:

- **Case-insensitive**: `leaving soon.jpg` matches `Leaving Soon`
- **Space/dash equivalence** (when `NORMALIZE_HYPHENS=true`): `leaving-soon.jpg` matches `Leaving Soon`
- **Multiple spaces/dashes**: `leaving---soon.jpg` matches `Leaving Soon`
- **Exact matching** (when `NORMALIZE_HYPHENS=false`): Hyphens and spaces are treated as different characters

Examples with `NORMALIZE_HYPHENS=true` (default):

- Image: `My-Favorite-Movies.jpg` → Matches collection: `My Favorite Movies`
- Image: `leaving soon.png` → Matches collection: `Leaving Soon`
- Image: `ACTION-MOVIES.jpg` → Matches collection: `Action Movies`

Examples with `NORMALIZE_HYPHENS=false`:

- Image: `My-Favorite-Movies.jpg` → Matches collection: `My-Favorite-Movies` (exact match)
- Image: `leaving soon.png` → Matches collection: `Leaving Soon` (spaces match, but won't match `Leaving-Soon`)

### Examples

The `examples/` folder contains resources to help you create custom collection posters:

- **`collection-name.png`** - Example poster image demonstrating:
  - Standard poster dimensions (1000x1500px)
  - Proper styling and text placement
  - Design reference for creating your own posters

- **`Poster Template.fig`** - Figma template file for:
  - Creating custom collection posters
  - Consistent styling across all your posters
  - Easy customization of colors, fonts, and layout

#### Creating Your Own Posters

1. Open `Poster Template.fig` in Figma (or use the example PNG as a reference)
2. Customize the design with your collection name
3. Export as JPG or PNG (1000x1500px recommended)
4. Name the file to match your collection name (e.g., `Leaving Soon.jpg`)
5. Place it in your posters folder

### Manual Execution

To manually run the sync script inside the container:

```bash
docker exec collection-poster-sync python /app/collection_poster_sync.py
```

### Logging

By default, logs are output to the console (stdout). View logs using Docker:

```bash
# Follow logs
docker logs -f collection-poster-sync

# View last 100 lines
docker logs --tail 100 collection-poster-sync
```

**Logging Configuration:**
- **Console output**: Always enabled, defaults to INFO level
- **File logging**: Optional, enabled by setting `LOG_PATH` environment variable
- **Log levels**: Control verbosity with `LOG_LEVEL` (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- **Debug mode**: Set `LOG_LEVEL=DEBUG` to see detailed debug information

**Note**: Debug messages (`[DBG]`) are hidden by default. Set `LOG_LEVEL=DEBUG` to enable verbose output for troubleshooting.

### Troubleshooting

#### Collection Not Found

- Verify the collection name matches the image filename (after normalization)
- Check that the collection exists in Plex
- Ensure the collection is visible (not hidden)

#### Poster Not Updating

- Check if `REAPPLY_POSTERS` is set to `false` and the poster hash matches
- Verify file permissions on the poster folder
- Check logs for specific error messages

#### Connection Issues

- Verify `PLEX_URL` is accessible from the container
- Ensure `PLEX_TOKEN` is valid and not expired
- Check network connectivity between container and Plex server

#### "New Device" Notifications

If you're receiving "new device" notifications from Plex every time the container restarts:

- The script uses `plexapi`'s supported environment variables (`PLEXAPI_HEADER_*`) to maintain a stable client identifier
- Set `PLEXAPI_HEADER_IDENTIFIER` to a consistent value (e.g., `"plex-collection-poster-sync"`) to prevent new device registrations
- After fixing, remove duplicate device entries in Plex: **Account → Authorized Devices**
- See `docker-compose.yml` for all available device identification environment variables

### Credits

This project was inspired by:

- **[maintainerr-overlay-helperr](https://github.com/gssariev/maintainerr-overlay-helperr)** by [@gssariev](https://github.com/gssariev)
- **[Maintainerr Poster Overlay](https://gitlab.com/jakeC207/maintainerr-poster-overlay)** by [@jakeC207](https://gitlab.com/jakeC207)

### License

[MIT](https://github.com/Rubeanie/plex-collection-poster-sync/blob/main/LICENSE)
