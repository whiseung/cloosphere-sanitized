import { WEBUI_API_BASE_URL } from '$lib/constants';

export const guideChat = async (
	token: string,
	messages: { role: string; content: string }[],
	modelId: string
) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/guide/chat`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			messages,
			model_id: modelId
		})
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err;
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};
