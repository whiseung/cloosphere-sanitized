import { WEBUI_API_BASE_URL } from '$lib/constants';

// Types

export type FlowNodeType =
	| 'flowInput'
	| 'flowOutput'
	| 'agent'
	| 'model'
	| 'condition'
	| 'router'
	| 'merge'
	| 'glossary'
	| 'transform'
	| 'guardrail';

// Agent node config
export type AgentConfig = {
	userPrompt?: string;                  // User prompt template with {state_key} placeholders
	outputKey?: string;                   // State key for output (default: "response")
};

// Model node config (simple LLM call without agent)
export type ModelConfig = {
	modelId?: string;                     // Model to use (e.g., "gpt-4", "claude-3")
	systemPrompt?: string;                // System prompt
	userPrompt?: string;                  // User prompt template with {state_key} placeholders
	temperature?: number;                 // 0.0 - 2.0
	maxTokens?: number;                   // Max output tokens
	responseFormat?: 'text' | 'json';     // Output format
	outputKey?: string;                   // State key for output (default: "response")
	// JSON output fields - each becomes a State key
	jsonFields?: Array<{
		name: string;                       // Field name = State key (e.g., "category")
		type: 'string' | 'number' | 'boolean' | 'array' | 'object';
		description?: string;               // Description for LLM
	}>;
};

// Condition node config
export type ConditionConfig = {
	conditionType: string;                // "contains", "equals", etc.
	value?: string;                       // Value to compare
	sourceField?: string;                 // State key to evaluate
};

// Router route definition
export type RouterRoute = {
	id: string;
	label: string;
	condition?: {
		type: string;   // "contains", "equals", "regex", etc.
		value?: string;
	};
};

// Router node config
export type RouterConfig = {
	routes: RouterRoute[];
	routingType: 'rule' | 'llm';
	defaultRoute?: string;
	sourceField?: string;
	modelId?: string;  // For LLM routing
};

// Guardrail node config (hybrid approach)
// Pass output: continues flow normally
// Block output: behavior depends on onBlocked setting
export type GuardrailConfig = {
	// Block action: what to do when guardrail blocks content
	onBlocked: 'stop' | 'message' | 'continue';
	// 'stop': End flow execution immediately
	// 'message': Show custom message and stop
	// 'continue': Continue to Block output with block info

	// Custom message to show when onBlocked is 'message'
	blockedMessage?: string;

	// Output State keys (default: guardrail_passed, guardrail_type, guardrail_reason)
	outputKeys?: {
		passed?: string;     // default: "guardrail_passed"
		type?: string;       // default: "guardrail_type"
		reason?: string;     // default: "guardrail_reason"
	};
};

// Transform node config (LangGraph compatible)
export type TransformConfig = {
	// Transform type
	transformType:
		| 'extract'      // Extract specific State key
		| 'format';      // Format text with template using State keys

	// For 'extract' type - which State key to extract
	sourceField?: string;               // State key to extract (e.g., "response", "guardrail_type")

	// For 'format' type - template with {state_key} placeholders
	formatTemplate?: string;            // e.g., "Error: {guardrail_type} - {guardrail_reason}"

	// Advanced: Raw Jinja2 template (for power users)
	useAdvanced?: boolean;
	template?: string;                  // Jinja2 template

	// Output State key
	outputKey?: string;                 // State key for output (default: "transformed")
};

export type FlowNode = {
	id: string;
	type: FlowNodeType;
	position: { x: number; y: number };
	data: {
		resourceId?: string;
		config?: Record<string, unknown> | AgentConfig | ConditionConfig | RouterConfig | ModelConfig | TransformConfig | GuardrailConfig;
		label?: string;
	};
};

export type FlowEdge = {
	id: string;
	source: string;
	target: string;
	sourceHandle?: string;
	targetHandle?: string;
	// LangGraph conversion fields
	label?: string;                       // UI display ("True", "승인됨")
	condition?: {
		branch_key: string;                 // LangGraph path_map key
	};
};

export type FlowData = {
	nodes: FlowNode[];
	edges: FlowEdge[];
	variables?: Record<string, unknown>;
	// LangGraph state schema (optional, for future use)
	state_schema?: Record<string, 'string' | 'list' | 'dict' | 'messages'>;
};

export type AgentFlowForm = {
	id: string;
	name: string;
	description?: string;
	flow_data?: FlowData;
	meta?: Record<string, unknown>;
	access_control?: object | null;
	is_active?: boolean;
};

export type AgentFlowUpdateForm = Partial<AgentFlowForm>;

export type AgentFlow = AgentFlowForm & {
	id: string;
	user_id: string;
	created_at: number;
	updated_at: number;
	user?: {
		id: string;
		name: string;
		email: string;
	};
};

export type FlowValidationError = {
	type: string;
	nodeId?: string;
	message: string;
};

export type FlowValidationResponse = {
	valid: boolean;
	errors: FlowValidationError[];
	warnings: FlowValidationError[];
};

// API Functions

export const getAgentFlows = async (token: string = ''): Promise<AgentFlow[]> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/agent-flows/`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail;
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getAgentFlowList = async (token: string = ''): Promise<AgentFlow[]> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/agent-flows/list`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail;
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getAgentFlowById = async (token: string, id: string): Promise<AgentFlow> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/agent-flows/${id}`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail;
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const checkFlowIdAvailable = async (
	token: string,
	flowId: string
): Promise<{ available: boolean }> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/agent-flows/check/${flowId}`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail;
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const createAgentFlow = async (token: string, form: AgentFlowForm): Promise<AgentFlow> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/agent-flows/create`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify(form)
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail;
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const updateAgentFlow = async (
	token: string,
	id: string,
	form: AgentFlowUpdateForm
): Promise<AgentFlow> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/agent-flows/${id}/update`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify(form)
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail;
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const deleteAgentFlowById = async (token: string, id: string): Promise<boolean> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/agent-flows/${id}/delete`, {
		method: 'DELETE',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail;
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const validateAgentFlow = async (
	token: string,
	flowData: FlowData
): Promise<FlowValidationResponse> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/agent-flows/validate`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ flow_data: flowData })
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail;
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const exportAgentFlow = async (
	token: string,
	id: string
): Promise<Record<string, unknown>> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/agent-flows/${id}/export`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail;
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const autoBuildFlowChat = async (
	token: string,
	messages: Array<{ role: string; content: string }>,
	modelId: string,
	flowName: string = '',
	flowId: string = ''
): Promise<{
	assistant_message: string;
	pending_input?: { question: string; options: string[] };
	flow_data?: { nodes: any[]; edges: any[] };
	flow_id?: string;
	flow_name?: string;
	flow_description?: string;
}> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/agent-flows/auto-build/chat`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			messages,
			model_id: modelId,
			flow_name: flowName,
			flow_id: flowId
		})
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail;
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const autoBuildAgentFlow = async (
	token: string,
	name: string,
	intent: string,
	modelId: string
): Promise<AgentFlow> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/agent-flows/auto-build`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ name, intent, model_id: modelId })
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail;
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const importAgentFlow = async (
	token: string,
	data: Record<string, unknown>,
	name?: string
): Promise<AgentFlow> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/agent-flows/import`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ data, name })
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail;
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};
