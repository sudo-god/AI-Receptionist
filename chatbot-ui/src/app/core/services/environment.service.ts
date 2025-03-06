import { Inject, Injectable, InjectionToken, Optional } from '@angular/core';

export const ENVIRONMENT = new InjectionToken<EnvironmentData>('environment');

export interface EnvironmentData {
    apiUrl: string;
}

@Injectable({
  providedIn: 'root',
})
export class EnvironmentService {
  readonly environment: EnvironmentData;

  // We need @Optional to be able start app without providing environment file
  constructor(@Optional() @Inject(ENVIRONMENT) environment: EnvironmentData) {
    this.environment = environment;
  }
}
