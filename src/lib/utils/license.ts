export function isFeatureAllowed(config: any, module: string): boolean {
	if (!config?.license?.enforcement_enabled) return true;
	return config?.license?.permissions?.[module] ?? false;
}
