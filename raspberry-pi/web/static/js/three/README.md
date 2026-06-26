# Three.js Local Copy

**Version**: 0.160.0  
**Source**: https://unpkg.com/three@0.160.0/

## Files

- `three.module.js` - Core Three.js library (ES6 module)
- `controls/OrbitControls.js` - Camera orbit controls addon

## Why Local?

The system needs to work **offline** in field deployment without internet access. Using CDN (unpkg.com) would require internet connection, which is not guaranteed in outdoor solar panel installations.

## Usage

The 3D visualization (`3d-visualization.html`) imports Three.js using ES6 modules:

```javascript
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
```

The import map in the HTML file maps these imports to local files:

```json
{
  "imports": {
    "three": "/static/js/three/three.module.js",
    "three/addons/": "/static/js/three/"
  }
}
```

## Update

To update Three.js to a newer version:

```bash
# Download new version
curl -o three.module.js https://unpkg.com/three@VERSION/build/three.module.js
curl -o controls/OrbitControls.js https://unpkg.com/three@VERSION/examples/jsm/controls/OrbitControls.js

# Update version in this README
```

Replace `VERSION` with the desired version (e.g., `0.161.0`).

## License

Three.js is licensed under the MIT License.  
See: https://github.com/mrdoob/three.js/blob/dev/LICENSE
