import { expectTypeOf, it } from 'vitest'
import type {
  CodeRunResult,
  Credential,
  ExampleInfo,
  ImportPreview,
  NodeDefinition,
  NodeExecution,
  RunRecord,
  ValidationIssue,
  VersionRecord,
  VersionSummary,
  WorkflowRecord,
  WorkflowSummary,
} from '../types/workflow'
import type { components } from './api.generated'

type S = components['schemas']
/** Field names the client expects but the server does not send (renamed or removed on the backend). */
type Missing<Server, Client> = Exclude<keyof Client, keyof Server>

// Compile-time checks, enforced by `pnpm typecheck`. If the backend contract changes and
// docs/api/openapi.json is regenerated (`pnpm gen:api`), a client type that still expects a field the
// server no longer sends stops compiling here. (Optionality is not compared: pydantic defaults make
// every response field optional in the schema although the server always sends it.)
it('every field the client relies on still exists in the server contract', () => {
  expectTypeOf<Missing<S['ExampleInfo'], ExampleInfo>>().toEqualTypeOf<never>()
  expectTypeOf<Missing<S['ValidationIssue'], ValidationIssue>>().toEqualTypeOf<never>()
  expectTypeOf<Missing<S['NodeDefinition'], NodeDefinition>>().toEqualTypeOf<never>()
  expectTypeOf<Missing<S['WorkflowSummary'], WorkflowSummary>>().toEqualTypeOf<never>()
  expectTypeOf<Missing<S['VersionSummary'], VersionSummary>>().toEqualTypeOf<never>()
  expectTypeOf<Missing<S['CredentialRecord'], Credential>>().toEqualTypeOf<never>()
  expectTypeOf<Missing<S['CodeRunResult'], CodeRunResult>>().toEqualTypeOf<never>()
  expectTypeOf<Missing<S['ImportPreview'], ImportPreview>>().toEqualTypeOf<never>()
  expectTypeOf<Missing<S['ImportSummary'], ImportPreview['summary']>>().toEqualTypeOf<never>()
  expectTypeOf<Missing<S['NodeExecution'], NodeExecution>>().toEqualTypeOf<never>()
  expectTypeOf<Missing<S['RunRecord'], RunRecord>>().toEqualTypeOf<never>()
  expectTypeOf<Missing<S['WorkflowRecord'], WorkflowRecord>>().toEqualTypeOf<never>()
  expectTypeOf<Missing<S['VersionRecord'], VersionRecord>>().toEqualTypeOf<never>()
})
