import { WEBUI_API_BASE_URL } from '$lib/constants';

export interface SmtpConfig {
	server: string;
	port: number;
	username: string;
	password: string;
	use_tls: boolean;
	use_ssl: boolean;
	from_address: string;
	from_name: string;
}

export interface SendGridConfig {
	api_key: string;
	from_address: string;
	from_name: string;
}

export interface AzureEmailConfig {
	connection_string: string;
	from_address: string;
	from_name: string;
}

export interface MsGraphConfig {
	tenant_id: string;
	client_id: string;
	client_secret: string;
	sender_email: string;
	from_name: string;
}

export interface EmailChannelConfig {
	name: string;
	engine: string; // "smtp" | "sendgrid" | "azure" | "msgraph"
	smtp: SmtpConfig;
	sendgrid: SendGridConfig;
	azure: AzureEmailConfig;
	msgraph: MsGraphConfig;
}

export interface WebhookChannelConfig {
	name: string;
	provider: string; // "slack" | "teams" | "discord" | "telegram"
	url: string;
	bot_token: string; // Telegram bot token
	chat_id: string; // Telegram chat ID
}

export interface NotificationConfig {
	emails: EmailChannelConfig[];
	webhooks: WebhookChannelConfig[];
	events: string[];
}

export interface TestResponse {
	success: boolean;
	message: string;
}

export interface NotificationChannelList {
	emails: { name: string; engine: string }[];
	webhooks: { name: string; provider: string }[];
}

export const getNotificationChannelList = async (
	token: string
): Promise<NotificationChannelList> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/notifications/channels`, {
		method: 'GET',
		headers: {
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.log(err);
			error = err.detail;
			return { emails: [], webhooks: [] };
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getNotificationConfig = async (token: string): Promise<NotificationConfig | null> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/notifications/config`, {
		method: 'GET',
		headers: {
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.log(err);
			error = err.detail;
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const updateNotificationConfig = async (
	token: string,
	config: NotificationConfig
): Promise<NotificationConfig | null> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/notifications/config`, {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify(config)
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.log(err);
			error = err.detail;
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const testEmailConnection = async (token: string, index = 0): Promise<TestResponse> => {
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/notifications/email/test-connection?index=${index}`,
		{
			method: 'POST',
			headers: {
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			}
		}
	)
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.log(err);
			return { success: false, message: err.detail || 'Connection test failed' };
		});

	return res;
};

export const sendTestEmail = async (
	token: string,
	to: string,
	index = 0
): Promise<TestResponse> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/notifications/email/test`, {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ to, index })
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.log(err);
			return { success: false, message: err.detail || 'Failed to send test email' };
		});

	return res;
};

export const testWebhook = async (token: string, index = 0): Promise<TestResponse> => {
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/notifications/webhook/test?index=${index}`,
		{
			method: 'POST',
			headers: {
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			}
		}
	)
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.log(err);
			return { success: false, message: err.detail || 'Webhook test failed' };
		});

	return res;
};
