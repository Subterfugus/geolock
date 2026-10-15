// The app's version comes from package.json, which the release bump already updates.
import pkg from '../package.json';

export const APP_VERSION: string = pkg.version;
