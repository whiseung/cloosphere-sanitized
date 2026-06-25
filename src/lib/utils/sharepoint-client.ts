import { PublicClientApplication, type AccountInfo } from '@azure/msal-browser';
import type { PopupRequest } from '@azure/msal-browser';
import { WEBUI_BASE_URL } from '$lib/constants';

interface SharePointConfig {
	clientId: string;
	tenantId: string;
	siteUrl: string;
}

interface DriveItem {
	id: string;
	name: string;
	folder?: { childCount: number };
	file?: { mimeType: string };
	size?: number;
	lastModifiedDateTime?: string;
	webUrl?: string;
	parentReference?: {
		driveId: string;
		id: string;
		path: string;
	};
}

interface Site {
	id: string;
	name: string;
	displayName: string;
	webUrl: string;
}

interface Drive {
	id: string;
	name: string;
	driveType: string;
	webUrl: string;
}

let config: SharePointConfig | null = null;
let msalInstance: PublicClientApplication | null = null;
let currentAccount: AccountInfo | null = null;

const GRAPH_BASE_URL = 'https://graph.microsoft.com/v1.0';

// Fetch SharePoint configuration from backend
async function getConfig(): Promise<SharePointConfig> {
	if (config) return config;

	const response = await fetch(`${WEBUI_BASE_URL}/api/config`, {
		credentials: 'include'
	});
	if (!response.ok) {
		throw new Error('Failed to fetch configuration from server. Please check if you are logged in.');
	}
	const data = await response.json();

	if (!data.sharepoint) {
		throw new Error('SharePoint configuration not available. Please log in and try again.');
	}

	if (!data.sharepoint.client_id || !data.sharepoint.tenant_id) {
		throw new Error('SharePoint configuration not complete. Please set ONEDRIVE_CLIENT_ID_BUSINESS and ONEDRIVE_SHAREPOINT_TENANT_ID in environment variables.');
	}

	config = {
		clientId: data.sharepoint.client_id,
		tenantId: data.sharepoint.tenant_id,
		siteUrl: data.sharepoint.site_url || ''
	};

	return config;
}

// Initialize MSAL with tenant-specific authority
async function initializeMsal(): Promise<PublicClientApplication> {
	if (msalInstance) return msalInstance;

	const cfg = await getConfig();

	const msalConfig = {
		auth: {
			clientId: cfg.clientId,
			authority: `https://login.microsoftonline.com/${cfg.tenantId}`,
			redirectUri: window.location.origin
		},
		cache: {
			cacheLocation: 'sessionStorage' as const,
			storeAuthStateInCookie: false
		}
	};

	msalInstance = new PublicClientApplication(msalConfig);
	await msalInstance.initialize();

	// Check for existing accounts
	const accounts = msalInstance.getAllAccounts();
	if (accounts.length > 0) {
		currentAccount = accounts[0];
		msalInstance.setActiveAccount(currentAccount);
	}

	return msalInstance;
}

// Get access token for Microsoft Graph API
async function getAccessToken(): Promise<string> {
	const msal = await initializeMsal();

	const scopes: PopupRequest = {
		scopes: ['Sites.Read.All', 'Files.Read.All', 'User.Read']
	};

	try {
		// Try silent token acquisition first
		if (currentAccount) {
			const response = await msal.acquireTokenSilent({
				...scopes,
				account: currentAccount
			});
			return response.accessToken;
		}
	} catch {
		// Silent acquisition failed, fall through to popup
	}

	// Fallback to interactive login
	try {
		const response = await msal.loginPopup(scopes);
		currentAccount = response.account;
		msal.setActiveAccount(currentAccount);

		const tokenResponse = await msal.acquireTokenSilent({
			...scopes,
			account: currentAccount
		});
		return tokenResponse.accessToken;
	} catch (error) {
		throw new Error(
			'Failed to authenticate with SharePoint: ' +
				(error instanceof Error ? error.message : String(error))
		);
	}
}

// Helper function for Graph API calls
async function graphFetch<T>(endpoint: string): Promise<T> {
	const token = await getAccessToken();
	const response = await fetch(`${GRAPH_BASE_URL}${endpoint}`, {
		headers: {
			Authorization: `Bearer ${token}`,
			'Content-Type': 'application/json'
		}
	});

	if (!response.ok) {
		const errorText = await response.text();
		throw new Error(`Graph API error (${response.status}): ${errorText}`);
	}

	return response.json();
}

// Get list of SharePoint sites the user has access to
export async function getSites(): Promise<Site[]> {
	const cfg = await getConfig();
	const sites: Site[] = [];

	console.log('SharePoint: Getting sites with config:', { siteUrl: cfg.siteUrl });

	// If a specific site URL is configured, try to get that site first
	if (cfg.siteUrl) {
		try {
			const url = new URL(cfg.siteUrl);
			const hostname = url.hostname;
			const pathParts = url.pathname.split('/').filter(Boolean);

			let siteEndpoint: string;
			if (pathParts.length >= 2 && pathParts[0] === 'sites') {
				// Site collection: /sites/SiteName
				siteEndpoint = `/sites/${hostname}:/sites/${pathParts[1]}`;
			} else {
				// Root site
				siteEndpoint = `/sites/${hostname}`;
			}

			console.log('SharePoint: Fetching configured site:', siteEndpoint);
			const site = await graphFetch<Site>(siteEndpoint);
			console.log('SharePoint: Got configured site:', site);
			sites.push(site);
		} catch (error) {
			console.warn('SharePoint: Failed to get configured site:', error);
		}
	}

	// Also search for all sites user has access to
	try {
		console.log('SharePoint: Searching all sites...');
		const response = await graphFetch<{ value: Site[] }>('/sites?search=*');
		console.log('SharePoint: Search response:', response);
		if (response.value && response.value.length > 0) {
			// Add sites that aren't already in the list
			for (const site of response.value) {
				if (!sites.find(s => s.id === site.id)) {
					sites.push(site);
				}
			}
		}
	} catch (error) {
		console.warn('SharePoint: Failed to search sites:', error);
	}

	// If still no sites, try to get user's followed sites
	if (sites.length === 0) {
		try {
			console.log('SharePoint: Trying followed sites...');
			const response = await graphFetch<{ value: Site[] }>('/me/followedSites');
			console.log('SharePoint: Followed sites response:', response);
			if (response.value) {
				sites.push(...response.value);
			}
		} catch (error) {
			console.warn('SharePoint: Failed to get followed sites:', error);
		}
	}

	console.log('SharePoint: Final sites list:', sites);
	return sites;
}

// Get document libraries (drives) for a site
export async function getDrives(siteId: string): Promise<Drive[]> {
	const response = await graphFetch<{ value: Drive[] }>(`/sites/${siteId}/drives`);
	return response.value;
}

// Get items (files and folders) in a drive or folder
export async function getItems(driveId: string, folderId?: string): Promise<DriveItem[]> {
	const endpoint = folderId
		? `/drives/${driveId}/items/${folderId}/children`
		: `/drives/${driveId}/root/children`;

	const response = await graphFetch<{ value: DriveItem[] }>(endpoint);

	// Sort: folders first, then files, alphabetically
	return response.value.sort((a, b) => {
		const aIsFolder = !!a.folder;
		const bIsFolder = !!b.folder;
		if (aIsFolder !== bIsFolder) {
			return aIsFolder ? -1 : 1;
		}
		return a.name.localeCompare(b.name);
	});
}

// Download a file from SharePoint
export async function downloadFile(driveId: string, itemId: string): Promise<Blob> {
	const token = await getAccessToken();

	// Get download URL
	const itemResponse = await fetch(`${GRAPH_BASE_URL}/drives/${driveId}/items/${itemId}`, {
		headers: {
			Authorization: `Bearer ${token}`
		}
	});

	if (!itemResponse.ok) {
		throw new Error('Failed to get file information');
	}

	const itemData = await itemResponse.json();
	const downloadUrl = itemData['@microsoft.graph.downloadUrl'];

	if (!downloadUrl) {
		throw new Error('Download URL not available for this file');
	}

	// Download the file
	const downloadResponse = await fetch(downloadUrl);
	if (!downloadResponse.ok) {
		throw new Error('Failed to download file');
	}

	return downloadResponse.blob();
}

// Get breadcrumb path for navigation
export async function getBreadcrumbs(
	driveId: string,
	folderId?: string
): Promise<{ id: string; name: string }[]> {
	if (!folderId) {
		return [{ id: 'root', name: 'Root' }];
	}

	const item = await graphFetch<DriveItem>(`/drives/${driveId}/items/${folderId}`);

	const breadcrumbs: { id: string; name: string }[] = [{ id: 'root', name: 'Root' }];

	// Note: We only show root and current folder in breadcrumbs
	// Full path navigation would require additional API calls

	breadcrumbs.push({ id: folderId, name: item.name });

	return breadcrumbs;
}

// Check if user is authenticated
export async function isAuthenticated(): Promise<boolean> {
	try {
		const msal = await initializeMsal();
		const accounts = msal.getAllAccounts();
		return accounts.length > 0;
	} catch {
		return false;
	}
}

// Sign out
export async function signOut(): Promise<void> {
	if (msalInstance && currentAccount) {
		await msalInstance.logoutPopup({
			account: currentAccount
		});
		currentAccount = null;
	}
}

// Utility: format file size
export function formatFileSize(bytes?: number): string {
	if (!bytes) return '';
	const units = ['B', 'KB', 'MB', 'GB'];
	let size = bytes;
	let unitIndex = 0;
	while (size >= 1024 && unitIndex < units.length - 1) {
		size /= 1024;
		unitIndex++;
	}
	return `${size.toFixed(1)} ${units[unitIndex]}`;
}

// Utility: format date
export function formatDate(dateString?: string): string {
	if (!dateString) return '';
	return new Date(dateString).toLocaleDateString();
}

// Export types
export type { SharePointConfig, DriveItem, Site, Drive };
