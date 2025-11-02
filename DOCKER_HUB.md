# Publishing to Docker Hub

This guide explains how to publish the plex-collection-poster-sync image to Docker Hub.

## Prerequisites

1. Docker Hub account ([Sign up here](https://hub.docker.com/signup))
2. Docker installed and running
3. Logged into Docker Hub from your terminal

## Build and Push Steps

1. **Login to Docker Hub**:
```bash
docker login
```

2. **Build the image**:
```bash
docker build -t rubeanie/plex-collection-poster-sync:latest .
```

3. **Tag the image** (optional, for versioning):
```bash
docker tag rubeanie/plex-collection-poster-sync:latest rubeanie/plex-collection-poster-sync:v1.0.0
```

4. **Push to Docker Hub**:
```bash
# Push latest tag
docker push rubeanie/plex-collection-poster-sync:latest

# Push version tag (if you created one)
docker push rubeanie/plex-collection-poster-sync:v1.0.0
```

## Docker Hub Repository Settings

1. Go to your repository on Docker Hub
2. Set description: "Automatically sync collection posters from a folder of images to Plex collections"
3. Add full description with features and usage instructions
4. Set visibility (Public or Private)
5. Enable "Builds" if you want automatic builds from GitHub (optional)

## Recommended Repository Description

```
Plex Collection Poster Sync - Automatically sync collection posters from a folder of images to Plex collections. Perfect for Plex media server users who want to customize their collection artwork.

Features:
- Automatic sync with configurable CRON scheduling
- Smart collection name matching (case-insensitive, optional hyphen normalization)
- Duplicate detection using SHA256 hash comparison
- Retry logic for robust error handling
- Supports jpg, jpeg, png, tbn formats
- Works with all Plex libraries (Movies, TV Shows, etc.)

Perfect for Plex users who want to:
- Add custom "Leaving Soon" posters to collections
- Sync collection artwork automatically
- Customize Plex collection posters from a folder

See README.md for full documentation and usage examples.
```

## Automated Builds (Optional)

To set up automated builds from GitHub:

1. Link your GitHub account in Docker Hub settings
2. Create a GitHub repository for this project
3. In Docker Hub, go to your repository → Builds → Configure Automated Builds
4. Select your GitHub repository and branch
5. Docker Hub will automatically build and push new images when you push code

## Updating the Image

When you make changes:

1. Update the version (if using version tags)
2. Build with the new tag:
```bash
docker build -t rubeanie/plex-collection-poster-sync:latest .
docker build -t rubeanie/plex-collection-poster-sync:v1.0.1 .
```

3. Push both tags:
```bash
docker push rubeanie/plex-collection-poster-sync:latest
docker push rubeanie/plex-collection-poster-sync:v1.0.1
```

## Testing Before Publishing

Test your image locally before pushing:

```bash
# Build
docker build -t rubeanie/plex-collection-poster-sync:latest .

# Test run
docker run --rm \
  -e PLEX_URL="http://localhost:32400" \
  -e PLEX_TOKEN="test-token" \
  -e POSTER_FOLDER="/posters" \
  -v /path/to/test/posters:/posters \
  rubeanie/plex-collection-poster-sync:latest
```

