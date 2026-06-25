/**
 * DbSphere DB type → CodeMirror SQL dialect name mapping.
 *
 * The dialect string is consumed by `CodeEditor.svelte` which dynamically
 * imports `@codemirror/lang-sql` and selects the matching dialect.
 *
 * Vendors without a dedicated lang-sql dialect fall back to "standard".
 */
export type SqlDialectName =
	| 'postgresql'
	| 'mysql'
	| 'mariadb'
	| 'mssql'
	| 'sqlite'
	| 'plsql'
	| 'cassandra'
	| 'standard';

const DB_TYPE_TO_DIALECT: Record<string, SqlDialectName> = {
	postgres: 'postgresql',
	postgresql: 'postgresql',
	pg: 'postgresql',
	mysql: 'mysql',
	mariadb: 'mariadb',
	mssql: 'mssql',
	sqlserver: 'mssql',
	'sql-server': 'mssql',
	sql_server: 'mssql',
	azure_synapse: 'mssql',
	synapse: 'mssql',
	azure_fabric: 'mssql',
	fabric: 'mssql',
	sqlite: 'sqlite',
	oracle: 'plsql',
	plsql: 'plsql',
	cassandra: 'cassandra',
	snowflake: 'standard',
	databricks: 'standard',
	bigquery: 'standard'
};

/**
 * Resolve a DbSphere DB type (e.g. "postgres", "snowflake") to a CodeMirror
 * SQL dialect name. Unknown vendors return "standard".
 */
export const resolveSqlDialect = (dbType: string | null | undefined): SqlDialectName => {
	if (!dbType) return 'standard';
	const normalised = dbType.toString().trim().toLowerCase();
	return DB_TYPE_TO_DIALECT[normalised] ?? 'standard';
};
