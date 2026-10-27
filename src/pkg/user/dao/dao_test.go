// Copyright Project Harbor Authors
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//    http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

package dao

import (
	"fmt"
	"testing"

	"github.com/stretchr/testify/suite"

	commonmodels "github.com/goharbor/harbor/src/common/models"
	"github.com/goharbor/harbor/src/lib/orm"
	"github.com/goharbor/harbor/src/lib/q"
	htesting "github.com/goharbor/harbor/src/testing"
)

type DaoTestSuite struct {
	htesting.Suite
	dao DAO
}

func (suite *DaoTestSuite) SetupSuite() {
	suite.Suite.SetupSuite()
	suite.ClearSQLs = []string{}
	suite.dao = New()
}

func (suite *DaoTestSuite) TestCount() {
	ctx := orm.Context()
	{
		n, err := suite.dao.Count(ctx, nil)
		suite.Nil(err)
		users, err := suite.dao.List(orm.Context(), nil)
		suite.Nil(err)
		suite.Equal(len(users), int(n))
	}
	{

		n, err := suite.dao.Count(ctx, nil)
		suite.Nil(err)
		id, err := suite.dao.Create(ctx, &commonmodels.User{
			Username:        "testuser2",
			Realname:        "user test",
			Email:           "testuser@test.com",
			Password:        "somepassword",
			PasswordVersion: "sha256",
		})
		suite.Nil(err)
		defer suite.appendClearSQL(id)
		n2, err := suite.dao.Count(ctx, nil)
		suite.Nil(err)
		suite.Equal(n+1, n2)
		err2 := suite.dao.Update(ctx, &commonmodels.User{
			UserID:  id,
			Deleted: true,
		})
		suite.Nil(err2)
		n3, err := suite.dao.Count(ctx, nil)
		suite.Nil(err)
		suite.Equal(n, n3)

	}

}

func (suite *DaoTestSuite) TestList() {
	ctx := orm.Context()
	{
		users, err := suite.dao.List(ctx, q.New(q.KeyWords{"user_id": 1}))
		suite.Nil(err)
		suite.Len(users, 1)
	}

	{
		users, err := suite.dao.List(ctx, q.New(q.KeyWords{"username": "admin"}))
		suite.Nil(err)
		suite.Len(users, 1)
	}
	id, err := suite.dao.Create(ctx, &commonmodels.User{
		Username:        "list_test",
		Realname:        "list test",
		Email:           "list_test@test.com",
		Password:        "somepassword",
		PasswordVersion: "sha256",
	})
	suite.appendClearSQL(id)
	suite.Nil(err)
	{
		users, err := suite.dao.List(ctx, q.New(q.KeyWords{"username_or_email": "list_test"}))
		suite.Nil(err)
		suite.Len(users, 1)
	}
	{
		users, err := suite.dao.List(ctx, q.New(q.KeyWords{"username_or_email": "list_test@test.com"}))
		suite.Nil(err)
		suite.Len(users, 1)
	}
	{
		users, err := suite.dao.List(ctx, q.New(q.KeyWords{"username_or_email": "noremail_norusername"}))
		suite.Nil(err)
		suite.Len(users, 0)
	}

}

func (suite *DaoTestSuite) TestCreate() {
	cases := []struct {
		name     string
		input    *commonmodels.User
		hasError bool
	}{
		{
			name: "create with user ID",
			input: &commonmodels.User{
				UserID:          3,
				Username:        "testuser",
				Realname:        "user test",
				Email:           "testuser@test.com",
				Password:        "somepassword",
				PasswordVersion: "sha256",
			},
			hasError: true,
		},
		{
			name: "create without user ID",
			input: &commonmodels.User{
				Username:        "testuser",
				Realname:        "user test",
				Email:           "testuser@test.com",
				Password:        "somepassword",
				PasswordVersion: "sha256",
			},
			hasError: false,
		},
		{
			name: "create with empty email_1",
			input: &commonmodels.User{
				Username:        "emptyemail1",
				Realname:        "empty test",
				Email:           "",
				Password:        "somepassword",
				PasswordVersion: "sha256",
			},
			hasError: false,
		},
		{
			name: "create with empty email_2",
			input: &commonmodels.User{
				Username:        "emptyemail2",
				Realname:        "empty test2",
				Email:           "",
				Password:        "somepassword",
				PasswordVersion: "sha256",
			},
			hasError: false,
		},
	}
	for _, c := range cases {
		suite.Run(c.name, func() {
			ctx := orm.Context()
			id, err := suite.dao.Create(ctx, c.input)
			defer suite.appendClearSQL(id)
			if c.hasError {
				suite.NotNil(err)
			} else {
				suite.Nil(err)
				l, err2 := suite.dao.List(ctx, q.New(q.KeyWords{"user_id": id}))
				suite.Nil(err2)
				suite.Equal(c.input.Username, l[0].Username)
				suite.Equal(c.input.Password, l[0].Password)
				suite.Equal(c.input.Email, l[0].Email)
				suite.Equal(c.input.Realname, l[0].Realname)
				suite.Equal(c.input.PasswordVersion, l[0].PasswordVersion)
			}
		})
	}
}

// TestEmployeeNumber covers the company-SSO column end to end: persisted on
// create, readable, updated by the partial "EmployeeNumber" backfill, and empty
// for users created by other auth modes.
func (suite *DaoTestSuite) TestEmployeeNumber() {
	ctx := orm.Context()
	id, err := suite.dao.Create(ctx, &commonmodels.User{
		Username:       "oidc-employee",
		Realname:       "杨皓翔",
		Email:          "oidc-employee@test.com",
		EmployeeNumber: "WXB0001",
	})
	suite.Require().Nil(err)
	defer suite.appendClearSQL(id)

	users, err := suite.dao.List(ctx, q.New(q.KeyWords{"user_id": id}))
	suite.Require().Nil(err)
	suite.Require().Len(users, 1)
	suite.Equal("WXB0001", users[0].EmployeeNumber)

	err = suite.dao.Update(ctx, &commonmodels.User{UserID: id, EmployeeNumber: "WXB0002"}, "EmployeeNumber")
	suite.Require().Nil(err)

	users, err = suite.dao.List(ctx, q.New(q.KeyWords{"user_id": id}))
	suite.Require().Nil(err)
	suite.Require().Len(users, 1)
	suite.Equal("WXB0002", users[0].EmployeeNumber)
	suite.Equal("oidc-employee", users[0].Username)
	suite.Equal("杨皓翔", users[0].Realname)

	otherID, err := suite.dao.Create(ctx, &commonmodels.User{Username: "db-auth-user", Email: "db-auth-user@test.com"})
	suite.Require().Nil(err)
	defer suite.appendClearSQL(otherID)
	other, err := suite.dao.List(ctx, q.New(q.KeyWords{"user_id": otherID}))
	suite.Require().Nil(err)
	suite.Require().Len(other, 1)
	suite.Empty(other[0].EmployeeNumber)
}

func (suite *DaoTestSuite) TestBackfillEmployeeNumber() {
	ctx := orm.Context()
	for _, initial := range []string{"", "existing-number"} {
		id, err := suite.dao.Create(ctx, &commonmodels.User{Username: "backfill-" + initial, EmployeeNumber: initial})
		suite.Require().NoError(err)
		defer suite.appendClearSQL(id)
		changed, err := suite.dao.BackfillEmployeeNumber(ctx, id, "first-number")
		suite.Require().NoError(err)
		suite.Equal(initial == "", changed)
		// A second callback using a stale empty snapshot must not replace the first value.
		changed, err = suite.dao.BackfillEmployeeNumber(ctx, id, "stale-number")
		suite.Require().NoError(err)
		suite.False(changed)
		users, err := suite.dao.List(ctx, q.New(q.KeyWords{"user_id": id}))
		suite.Require().NoError(err)
		suite.Require().Len(users, 1)
		want := initial
		if want == "" {
			want = "first-number"
		}
		suite.Equal(want, users[0].EmployeeNumber)
	}
	// Legacy empty strings and NULL both mean the value has not been backfilled.
	id, err := suite.dao.Create(ctx, &commonmodels.User{Username: "backfill-empty-string"})
	suite.Require().NoError(err)
	defer suite.appendClearSQL(id)
	suite.Require().NoError(suite.dao.Update(ctx, &commonmodels.User{UserID: id}, "EmployeeNumber"))
	o, err := orm.FromContext(ctx)
	suite.Require().NoError(err)
	_, err = o.Raw("UPDATE harbor_user SET employee_number = '' WHERE user_id = ?", id).Exec()
	suite.Require().NoError(err)
	changed, err := suite.dao.BackfillEmployeeNumber(ctx, id, "legacy-number")
	suite.Require().NoError(err)
	suite.True(changed)
}

func (suite *DaoTestSuite) appendClearSQL(uid int) {
	suite.ClearSQLs = append(suite.ClearSQLs, fmt.Sprintf("DELETE FROM harbor_user WHERE user_id = %d", uid))
}

func (suite *DaoTestSuite) TestSearchByName() {
	// prepare data
	ctx := orm.Context()
	// insert some other users
	for i := 0; i < 20; i++ {
		id, err := suite.dao.Create(ctx, &commonmodels.User{
			Username: fmt.Sprintf("searchbyname_%d", i),
			Realname: "search by name test",
		})
		suite.Nil(err)
		suite.appendClearSQL(id)
	}
	// insert the target user
	id, err := suite.dao.Create(ctx, &commonmodels.User{
		Username: "searchbyname",
		Realname: "search by name test",
	})
	suite.Nil(err)
	suite.appendClearSQL(id)

	// search by name, the first 10 records should be returned
	users, err := suite.dao.SearchByName(ctx, "searchbyname", 10)
	suite.Nil(err)
	suite.Len(users, 10)

	// the first record should be the target user
	suite.Equal("searchbyname", users[0].Username)

}

func TestDaoTestSuite(t *testing.T) {
	suite.Run(t, &DaoTestSuite{})
}
