import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { permissionsApi, teamApi } from '../services/api'

interface BoardMember {
  id: string
  user_id: string
  board_id: string
  role: 'owner' | 'admin' | 'member' | 'viewer'
  name?: string
  email?: string
  added_at: string
}

interface TeamMember {
  id: string
  email: string
  name: string
  role: string
  is_active: boolean
}

interface BoardPermissionsModalProps {
  boardId: string
  boardName: string
  isOpen: boolean
  onClose: () => void
}

export default function BoardPermissionsModal({ boardId, boardName, isOpen, onClose }: BoardPermissionsModalProps) {
  const queryClient = useQueryClient()
  const [showAddMember, setShowAddMember] = useState(false)
  const [selectedMemberId, setSelectedMemberId] = useState('')
  const [selectedRole, setSelectedRole] = useState<'admin' | 'member' | 'viewer'>('member')
  const [searchQuery, setSearchQuery] = useState('')

  const { data: membersData, isLoading } = useQuery({
    queryKey: ['board-members', boardId],
    queryFn: () => permissionsApi.listMembers(boardId).then(res => res.data),
    enabled: isOpen
  })

  const { data: teamMembersData } = useQuery({
    queryKey: ['team-members-all'],
    queryFn: () => teamApi.listMembers().then(res => res.data),
    enabled: isOpen && showAddMember
  })

  const addMemberMutation = useMutation({
    mutationFn: (data: { user_id: string; role: string }) =>
      permissionsApi.addMember(boardId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['board-members', boardId] })
      setShowAddMember(false)
      setSelectedMemberId('')
      setSelectedRole('member')
    }
  })

  const updateMemberMutation = useMutation({
    mutationFn: ({ memberId, role }: { memberId: string; role: string }) =>
      permissionsApi.updateMember(boardId, memberId, { role }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['board-members', boardId] })
    }
  })

  const removeMemberMutation = useMutation({
    mutationFn: (memberId: string) => permissionsApi.removeMember(boardId, memberId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['board-members', boardId] })
    }
  })

  const roleColors: Record<string, string> = {
    owner: 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200',
    admin: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
    member: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
    viewer: 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-200'
  }

  const roleDescriptions: Record<string, string> = {
    owner: 'Full control, can delete board and transfer ownership',
    admin: 'Can manage members and board settings',
    member: 'Can create and edit cards',
    viewer: 'Can only view the board'
  }

  if (!isOpen) return null

  const boardMembers: BoardMember[] = membersData?.members || []
  const teamMembers: TeamMember[] = teamMembersData?.members || []

  // Filter team members who are not already board members
  const boardMemberIds = new Set(boardMembers.map(m => m.user_id))
  const availableMembers = teamMembers
    .filter(m => m.is_active && !boardMemberIds.has(m.id))
    .filter(m => {
      if (!searchQuery) return true
      const query = searchQuery.toLowerCase()
      return m.name.toLowerCase().includes(query) || m.email.toLowerCase().includes(query)
    })

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl w-full max-w-2xl max-h-[80vh] flex flex-col">
        {/* Header */}
        <div className="px-6 py-4 border-b dark:border-gray-700 flex items-center justify-between">
          <div>
            <h2 className="text-xl font-bold dark:text-white">Board Permissions</h2>
            <p className="text-sm text-gray-500">{boardName}</p>
          </div>
          <button
            onClick={onClose}
            className="p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg"
          >
            <svg className="w-5 h-5 dark:text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6">
          {isLoading ? (
            <div className="flex items-center justify-center h-32">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
            </div>
          ) : (
            <>
              {/* Add Member Button */}
              {!showAddMember && (
                <button
                  onClick={() => setShowAddMember(true)}
                  className="w-full mb-4 px-4 py-3 border-2 border-dashed border-gray-300 dark:border-gray-600 rounded-lg text-gray-500 hover:border-blue-500 hover:text-blue-500 transition-colors flex items-center justify-center gap-2"
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M18 9v3m0 0v3m0-3h3m-3 0h-3m-2-5a4 4 0 11-8 0 4 4 0 018 0zM3 20a6 6 0 0112 0v1H3v-1z" />
                  </svg>
                  Add team member to board
                </button>
              )}

              {/* Add Member Form */}
              {showAddMember && (
                <div className="mb-4 p-4 bg-gray-50 dark:bg-gray-700 rounded-lg">
                  <h3 className="font-medium mb-3 dark:text-white">Add Member to Board</h3>
                  <div className="space-y-3">
                    <div>
                      <input
                        type="text"
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        placeholder="Search team members..."
                        className="w-full px-3 py-2 border rounded-lg dark:bg-gray-600 dark:border-gray-500 dark:text-white"
                      />
                    </div>
                    {availableMembers.length > 0 ? (
                      <div className="max-h-40 overflow-y-auto space-y-1">
                        {availableMembers.slice(0, 10).map((member) => (
                          <button
                            key={member.id}
                            onClick={() => setSelectedMemberId(member.id)}
                            className={`w-full text-left px-3 py-2 rounded-lg flex items-center gap-3 ${
                              selectedMemberId === member.id
                                ? 'bg-blue-100 dark:bg-blue-900'
                                : 'hover:bg-gray-100 dark:hover:bg-gray-600'
                            }`}
                          >
                            <div className="w-8 h-8 rounded-full bg-gray-200 dark:bg-gray-500 flex items-center justify-center text-sm font-medium">
                              {member.name?.charAt(0)?.toUpperCase() || '?'}
                            </div>
                            <div>
                              <div className="font-medium dark:text-white">{member.name}</div>
                              <div className="text-sm text-gray-500">{member.email}</div>
                            </div>
                          </button>
                        ))}
                      </div>
                    ) : (
                      <p className="text-sm text-gray-500 py-2">
                        {searchQuery ? 'No members found' : 'All team members already have access'}
                      </p>
                    )}
                    {selectedMemberId && (
                      <div>
                        <label className="block text-sm font-medium mb-1 dark:text-white">Role</label>
                        <select
                          value={selectedRole}
                          onChange={(e) => setSelectedRole(e.target.value as typeof selectedRole)}
                          className="w-full px-3 py-2 border rounded-lg dark:bg-gray-600 dark:border-gray-500 dark:text-white"
                        >
                          <option value="admin">Admin</option>
                          <option value="member">Member</option>
                          <option value="viewer">Viewer</option>
                        </select>
                      </div>
                    )}
                    <div className="flex justify-end gap-2">
                      <button
                        onClick={() => {
                          setShowAddMember(false)
                          setSelectedMemberId('')
                          setSearchQuery('')
                        }}
                        className="px-3 py-1.5 text-gray-600 hover:bg-gray-200 rounded dark:text-gray-300 dark:hover:bg-gray-600"
                      >
                        Cancel
                      </button>
                      <button
                        onClick={() => addMemberMutation.mutate({ user_id: selectedMemberId, role: selectedRole })}
                        disabled={!selectedMemberId || addMemberMutation.isPending}
                        className="px-3 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
                      >
                        {addMemberMutation.isPending ? 'Adding...' : 'Add to Board'}
                      </button>
                    </div>
                  </div>
                </div>
              )}

              {/* Members List */}
              <div className="space-y-2">
                {boardMembers.map((member) => (
                  <div
                    key={member.id}
                    className="flex items-center justify-between p-3 bg-gray-50 dark:bg-gray-700 rounded-lg"
                  >
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 rounded-full bg-gray-200 dark:bg-gray-600 flex items-center justify-center text-lg font-medium">
                        {member.name?.charAt(0)?.toUpperCase() || '?'}
                      </div>
                      <div>
                        <div className="font-medium dark:text-white">{member.name || 'Unknown'}</div>
                        <div className="text-sm text-gray-500">{member.email}</div>
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      {member.role === 'owner' ? (
                        <span className={`px-2 py-1 rounded-full text-xs font-medium ${roleColors[member.role]}`}>
                          {member.role}
                        </span>
                      ) : (
                        <select
                          value={member.role}
                          onChange={(e) => updateMemberMutation.mutate({
                            memberId: member.id,
                            role: e.target.value
                          })}
                          className={`px-2 py-1 rounded-full text-xs font-medium border-0 cursor-pointer ${roleColors[member.role]}`}
                        >
                          <option value="admin">admin</option>
                          <option value="member">member</option>
                          <option value="viewer">viewer</option>
                        </select>
                      )}
                      {member.role !== 'owner' && (
                        <button
                          onClick={() => {
                            if (confirm(`Remove ${member.name || 'this member'} from the board?`)) {
                              removeMemberMutation.mutate(member.id)
                            }
                          }}
                          className="p-1 hover:bg-red-100 dark:hover:bg-red-900 rounded text-red-600"
                          title="Remove from board"
                        >
                          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                          </svg>
                        </button>
                      )}
                    </div>
                  </div>
                ))}

                {boardMembers.length === 0 && (
                  <p className="text-center text-gray-500 py-8">
                    No members have been added to this board yet.
                    <br />
                    <span className="text-sm">All team members can access this board by default.</span>
                  </p>
                )}
              </div>

              {/* Role Descriptions */}
              <div className="mt-6 p-4 bg-gray-50 dark:bg-gray-700 rounded-lg">
                <h4 className="font-medium mb-2 dark:text-white">Role Permissions</h4>
                <div className="space-y-2 text-sm">
                  {Object.entries(roleDescriptions).map(([role, description]) => (
                    <div key={role} className="flex items-start gap-2">
                      <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${roleColors[role]}`}>
                        {role}
                      </span>
                      <span className="text-gray-600 dark:text-gray-300">{description}</span>
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
