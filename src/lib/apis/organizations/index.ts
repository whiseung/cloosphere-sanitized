import { WEBUI_API_BASE_URL } from '$lib/constants';

export interface Organization {
	id: string;
	tenant_id: string;
	name: string;
	display_name: string | null;
	domain: string | null;
	meta: Record<string, unknown> | null;
	created_at: number;
	updated_at: number;
}

export interface OrganizationalUnit {
	id: string;
	organization_id: string;
	parent_id: string | null;
	name: string;
	display_name: string | null;
	description: string | null;
	level: number;
	type: string | null;
	external_id: string | null;
	member_ids: string[];
	meta: Record<string, unknown> | null;
	created_at: number;
	updated_at: number;
	children?: OrganizationalUnit[]; // For tree structure
}

export interface SyncProvider {
	type: string;
	name: string;
	description: string;
	requires?: string[];
}

export interface SyncResult {
	success: boolean;
	result: {
		organization: { created: number; updated: number };
		units: { created: number; updated: number; deleted: number };
	};
}

export const getOrganizations = async (token: string): Promise<Organization[]> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/organizations/`, {
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
			error = err;
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res ?? [];
};

export const getOrganizationById = async (token: string, id: string): Promise<Organization | null> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/organizations/${id}`, {
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
			error = err;
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const createOrganization = async (
	token: string,
	organization: Partial<Organization>
): Promise<Organization | null> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/organizations/`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify(organization)
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

export const updateOrganization = async (
	token: string,
	id: string,
	organization: Partial<Organization>
): Promise<Organization | null> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/organizations/${id}`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify(organization)
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

export const deleteOrganization = async (token: string, id: string): Promise<boolean> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/organizations/${id}`, {
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
			error = err;
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getOrganizationalUnits = async (
	token: string,
	organizationId?: string
): Promise<OrganizationalUnit[]> => {
	let error = null;
	const url = organizationId
		? `${WEBUI_API_BASE_URL}/organizations/${organizationId}/units`
		: `${WEBUI_API_BASE_URL}/organizations/units`;

	const res = await fetch(url, {
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
			error = err;
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res ?? [];
};

export const getOrgUnitMemberEmails = async (
	token: string,
	id: string
): Promise<Array<{ name: string; email: string }>> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/organizations/units/${id}/member-emails`, {
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
			error = err;
			console.log(err);
			return null;
		});

	if (error) throw error;
	return res ?? [];
};

export const createOrganizationalUnit = async (
	token: string,
	unit: Partial<OrganizationalUnit>
): Promise<OrganizationalUnit | null> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/organizations/units`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify(unit)
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

export const updateOrganizationalUnit = async (
	token: string,
	id: string,
	unit: Partial<OrganizationalUnit>
): Promise<OrganizationalUnit | null> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/organizations/units/${id}`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify(unit)
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

export const deleteOrganizationalUnit = async (token: string, id: string): Promise<boolean> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/organizations/units/${id}`, {
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
			error = err;
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

// Tree structure
export const getOrganizationalUnitsTree = async (
	token: string,
	organizationId: string
): Promise<OrganizationalUnit[]> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/organizations/${organizationId}/units/tree`, {
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
			error = err;
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res ?? [];
};

// Sync APIs
export const getSyncProviders = async (token: string): Promise<{ providers: SyncProvider[] }> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/organizations/sync/providers`, {
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
			error = err;
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res ?? { providers: [] };
};

export interface JsonSyncData {
	organization: {
		tenant_id: string;
		name: string;
		display_name?: string;
		domain?: string;
	};
	units?: Array<{
		id?: string;
		name: string;
		type?: string;
		description?: string;
		children?: Array<unknown>;
	}>;
}

export const syncFromJson = async (token: string, data: JsonSyncData): Promise<SyncResult> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/organizations/sync/json`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify(data)
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

export interface MSGraphSyncOptions {
	access_token?: string;
	use_admin_units?: boolean;
	use_groups?: boolean;
	use_departments?: boolean;
	group_filter?: string;
}

export const syncFromMSGraph = async (
	token: string,
	options: MSGraphSyncOptions = {}
): Promise<SyncResult> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/organizations/sync/msgraph`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify(options)
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

export interface KeycloakSyncOptions {
	use_groups?: boolean;
	use_organizations?: boolean;
	group_filter?: string;
}

export const syncFromKeycloak = async (
	token: string,
	options: KeycloakSyncOptions
): Promise<SyncResult> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/organizations/sync/keycloak`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify(options)
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

export interface GoogleSyncOptions {
	use_org_units?: boolean;
	use_groups?: boolean;
}

export const syncFromGoogle = async (
	token: string,
	options: GoogleSyncOptions
): Promise<SyncResult> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/organizations/sync/google`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify(options)
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

// Permission types
export interface ResourcePermission {
	id: string;
	name: string;
	description?: string;
	read: boolean;
	write: boolean;
	inherited: boolean;
}

export interface UnitPermissions {
	unit_id: string;
	unit_name: string;
	permissions: {
		knowledge: ResourcePermission[];
		tools: ResourcePermission[];
		prompts: ResourcePermission[];
		models: ResourcePermission[];
		databases: ResourcePermission[];
		glossaries: ResourcePermission[];
		guardrails: ResourcePermission[];
	};
	ancestor_ids: string[];
}

export const getOrganizationalUnitPermissions = async (
	token: string,
	unitId: string
): Promise<UnitPermissions> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/organizations/units/${unitId}/permissions`, {
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
			error = err;
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getUnitGuardrails = async (token: string, unitId: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/organizations/units/${unitId}/guardrails`, {
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
			error = err;
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const updateUnitGuardrails = async (
	token: string,
	unitId: string,
	guardrailIds: string[],
	followGlobal: boolean
) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/organizations/units/${unitId}/guardrails`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			guardrail_ids: guardrailIds,
			follow_global: followGlobal
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

export const getOrgUnitUsageLimit = async (token: string, unitId: string) => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/organizations/units/${unitId}/usage-limit`, {
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
			console.log(err);
			error = err.detail;
			return null;
		});
	if (error) throw error;
	return res;
};

export const updateOrgUnitUsageLimit = async (
	token: string,
	unitId: string,
	perModel: Record<string, number>
) => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/organizations/units/${unitId}/usage-limit`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ per_model: perModel })
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
	if (error) throw error;
	return res;
};
