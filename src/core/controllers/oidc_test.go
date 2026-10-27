package controllers

import (
	"context"
	"errors"
	"testing"

	"github.com/stretchr/testify/assert"

	"github.com/goharbor/harbor/src/common/models"
	ctluser "github.com/goharbor/harbor/src/controller/user"
	"github.com/goharbor/harbor/src/pkg/oidc"
	mockuser "github.com/goharbor/harbor/src/testing/controller/user"
)

func TestBackfillEmployeeNumber(t *testing.T) {
	original := ctluser.Ctl
	t.Cleanup(func() { ctluser.Ctl = original })
	for _, tc := range []struct {
		name     string
		existing string
		claim    string
		write    bool
		err      error
		want     string
	}{
		{name: "backfill empty", claim: " WXB0001 ", write: true, want: "WXB0001"},
		{name: "preserve existing", existing: "WXB0001", claim: "WXB9999", want: "WXB0001"},
		{name: "ignore blank", claim: "  "},
		{name: "leave empty on failure", claim: "WXB0001", write: true, err: errors.New("database unavailable")},
	} {
		t.Run(tc.name, func(t *testing.T) {
			controller := &mockuser.Controller{}
			ctluser.Ctl = controller
			ctx := context.Background()
			if tc.write {
				controller.On("BackfillEmployeeNumber", ctx, 42, "WXB0001").Return(tc.err == nil, tc.err).Once()
			}
			u := &models.User{UserID: 42, EmployeeNumber: tc.existing}
			backfillEmployeeNumber(ctx, u, &oidc.UserInfo{EmployeeNumber: tc.claim})
			assert.Equal(t, tc.want, u.EmployeeNumber)
			controller.AssertExpectations(t)
			if !tc.write {
				controller.AssertNotCalled(t, "BackfillEmployeeNumber")
			}
		})
	}
}

func TestGetSessionType(t *testing.T) {
	tests := []struct {
		name          string
		refreshToken  string
		expectedType  string
		expectedError bool
	}{
		{
			name:          "Valid",
			refreshToken:  "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0eXAiOiJvZmZsaW5lIn0.d9fcdba7c10fc1263bf682947afabaecf3496070cd2d5a5e7b3c79dbf1545c1f",
			expectedType:  "offline",
			expectedError: false,
		},
		{
			name:          "Invalid",
			refreshToken:  "invalidToken",
			expectedType:  "",
			expectedError: true,
		},
		{
			name:          "Missing 'typ' claim",
			refreshToken:  "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhbGciOiJIUzI1NiJ9.d9fcdba7c10fc1263bf682947afabaecf3496070cd2d5a5e7b3c79dbf1545c1f",
			expectedType:  "",
			expectedError: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			typ, err := getSessionType(tt.refreshToken)
			if tt.expectedError {
				assert.Error(t, err)
				assert.Equal(t, tt.expectedType, typ)
			} else {
				assert.NoError(t, err)
				assert.Equal(t, tt.expectedType, typ)
			}
		})
	}
}
